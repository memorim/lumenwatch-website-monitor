"""One-shot, networkless browser containers with a bounded public HTTP broker."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import json
import os
import re
import socket
import struct
import uuid
from pathlib import Path
from time import perf_counter

import httpx

from app.diff_engine import normalize_text
from app.models import CaptureResult
from app.probes import ProbeError, validate_url

MAX_RESOURCE = 2 * 1024 * 1024
MAX_TOTAL = 10 * 1024 * 1024
MAX_LINE = 4 * 1024 * 1024
DEADLINE = 40


class PublicResourceBroker:
    def __init__(self) -> None:
        self.requests = 0
        self.total_bytes = 0

    async def fetch(self, raw_url: str, method: str) -> dict:
        self.requests += 1
        if self.requests > 64:
            raise ProbeError("Browser exceeded 64 resource requests.")
        if method not in {"GET", "HEAD"} or len(raw_url) > 4096:
            raise ProbeError("Only bounded read-only resource requests are allowed.")
        validate_url(raw_url)
        url = httpx.URL(raw_url)
        if url.port not in {None, 80, 443}:
            raise ProbeError("Only standard public HTTP(S) ports are allowed.")
        addresses = await asyncio.get_running_loop().getaddrinfo(
            url.host,
            url.port or (443 if url.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
        if not addresses or any(
            not ipaddress.ip_address(item[4][0]).is_global for item in addresses
        ):
            raise ProbeError("Only public network targets are allowed.")
        # DNS is resolved once per request and the vetted IP is used by the socket.
        pinned = url.copy_with(host=addresses[0][4][0])
        host = url.netloc.decode("ascii")
        async with httpx.AsyncClient(timeout=8, follow_redirects=False, trust_env=False) as client:
            async with client.stream(
                method,
                pinned,
                headers={
                    "Host": host,
                    "Accept-Encoding": "identity",
                    "User-Agent": "LumenWatch/1.0",
                },
                extensions={"sni_hostname": url.host},
            ) as response:
                if sum(len(k) + len(v) for k, v in response.headers.raw) > 16 * 1024:
                    raise ProbeError("Resource headers exceed 16 KiB.")
                headers = {
                    key: value
                    for key, value in response.headers.items()
                    if key in {"content-type", "location", "access-control-allow-origin"}
                }
                if response.has_redirect_location:
                    # Do not buffer redirects. Chromium's next request is brokered again.
                    return {"status": response.status_code, "headers": headers, "body": ""}
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ProbeError("Compressed resources are not supported.")
                body = bytearray()
                async for chunk in response.aiter_raw():
                    self.total_bytes += len(chunk)
                    if len(body) + len(chunk) > MAX_RESOURCE or self.total_bytes > MAX_TOTAL:
                        raise ProbeError("Browser resource byte budget exceeded.")
                    body.extend(chunk)
                return {
                    "status": response.status_code,
                    "headers": headers,
                    "body": base64.b64encode(body).decode("ascii"),
                }


def container_command(image: str, name: str) -> list[str]:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:@-]{0,240}", image):
        raise ProbeError("Invalid isolated browser image.")
    return [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--name",
        name,
        "--init",
        "--interactive",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--user=1000:1000",
        "--memory=768m",
        "--memory-swap=768m",
        "--cpus=1",
        "--pids-limit=128",
        "--shm-size=128m",
        "--tmpfs=/tmp:rw,nosuid,nodev,size=128m,mode=1777",
        "--ulimit=nofile=1024:1024",
        "--log-driver=none",
        image,
    ]


class IsolatedBrowserProbe:
    def __init__(self, capture_directory: Path) -> None:
        self.capture_directory = capture_directory

    async def capture(self, url: str, target_id: str) -> CaptureResult:
        validate_url(url)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", target_id):
            raise ProbeError("Invalid capture identifier.")
        image = os.getenv("LUMENWATCH_ISOLATED_BROWSER_IMAGE", "")
        if not image:
            raise ProbeError("Configure an isolated browser image first.")
        name = "lumenwatch-capture-" + uuid.uuid4().hex
        process = None
        started = perf_counter()
        try:
            async with asyncio.timeout(DEADLINE):
                process = await asyncio.create_subprocess_exec(
                    *container_command(image, name),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    limit=MAX_LINE,
                )
                result = await self.exchange(process, url, PublicResourceBroker())
                code = await process.wait()
                if code:
                    raise ProbeError("Isolated browser exited unsuccessfully.")
        except (TimeoutError, OSError, ValueError, KeyError, TypeError, httpx.HTTPError) as error:
            raise ProbeError("Isolated browser failed or exceeded its deadline.") from error
        finally:
            if process:
                # docker CLI termination alone does not guarantee container termination.
                try:
                    cleanup = await asyncio.create_subprocess_exec(
                        "docker",
                        "rm",
                        "--force",
                        name,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    try:
                        await asyncio.wait_for(cleanup.wait(), 5)
                    except TimeoutError:
                        cleanup.kill()
                        await cleanup.wait()
                finally:
                    if process.returncode is None:
                        process.kill()
                        await process.wait()
        screenshot = base64.b64decode(result["png"], validate=True)
        if not screenshot.startswith(b"\x89PNG\r\n\x1a\n") or len(screenshot) > MAX_RESOURCE:
            raise ProbeError("Invalid screenshot from browser worker.")
        if len(screenshot) < 24 or struct.unpack(">II", screenshot[16:24]) != (1440, 1000):
            raise ProbeError("Unexpected screenshot dimensions.")
        directory = self.capture_directory / target_id
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / "latest.png"
        temporary = directory / (uuid.uuid4().hex + ".tmp")
        temporary.write_bytes(screenshot)
        temporary.replace(destination)
        title = normalize_text(str(result["title"])[:1000])
        text = normalize_text(str(result["text"])[:120000])
        status = int(result["status"])
        if not 100 <= status <= 599:
            raise ProbeError("Invalid capture status.")
        return CaptureResult(
            status_code=status,
            title=title,
            content_text=text,
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
            response_ms=round((perf_counter() - started) * 1000),
            engine="playwright-isolated",
            screenshot_path=str(destination),
        )

    @staticmethod
    async def exchange(process, url: str, broker: PublicResourceBroker) -> dict:
        async def reply(value):
            process.stdin.write(json.dumps(value).encode() + b"\n")
            await process.stdin.drain()

        await reply({"url": url})
        for _ in range(65):
            line = await process.stdout.readline()
            if not line or len(line) > MAX_LINE:
                raise ProbeError("Invalid browser worker output.")
            message = json.loads(line)
            if message.get("kind") == "result":
                return message
            if message.get("kind") != "request":
                raise ProbeError("Browser capture failed.")
            # No worker-provided headers, paths or credentials cross this boundary.
            response = await broker.fetch(message["url"], message["method"])
            await reply(response)
        raise ProbeError("Browser request limit exceeded.")
