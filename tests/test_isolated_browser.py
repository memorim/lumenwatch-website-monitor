import asyncio
import base64
import json
import os
import subprocess
import uuid
from pathlib import Path

import httpx
import pytest

from app.isolated_browser import IsolatedBrowserProbe, PublicResourceBroker, container_command
from app.probes import ProbeError


class FixtureStream(httpx.AsyncByteStream):
    def __init__(self, content):
        self.content = content

    async def __aiter__(self):
        yield self.content


def transport(monkeypatch, handler, addresses=None):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real_client(**kw, transport=httpx.MockTransport(handler))
    )

    async def resolve(*_args, **_kwargs):
        return [(2, 1, 6, "", (address, 443)) for address in (addresses or ["8.8.8.8"])]

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", resolve)


def test_broker_rejects_private_dns_and_write_requests(monkeypatch):
    transport(monkeypatch, lambda _: pytest.fail("must not connect"), ["8.8.8.8", "127.0.0.1"])
    for url, method in [
        ("https://example.test", "GET"),
        ("https://example.test", "POST"),
        ("file:///etc/passwd", "GET"),
        ("https://user:secret@example.test", "GET"),
        ("https://example.test:8443", "GET"),
    ]:
        with pytest.raises(ProbeError):
            asyncio.run(PublicResourceBroker().fetch(url, method))


def test_broker_pins_address_and_strips_cookies(monkeypatch):
    def handler(request):
        assert request.url.host == "8.8.8.8"
        assert request.headers["Host"] == "example.test"
        assert request.extensions["sni_hostname"] == "example.test"
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html", "Set-Cookie": "secret=x"},
            stream=FixtureStream(b"<p>Public</p>"),
        )

    transport(monkeypatch, handler)
    result = asyncio.run(PublicResourceBroker().fetch("https://example.test", "GET"))
    assert result["headers"] == {"content-type": "text/html"}
    assert base64.b64decode(result["body"]) == b"<p>Public</p>"


def test_resource_and_request_budgets(monkeypatch):
    transport(
        monkeypatch,
        lambda _: httpx.Response(200, stream=FixtureStream(b"x" * (2 * 1024 * 1024 + 1))),
    )
    with pytest.raises(ProbeError, match="byte budget"):
        asyncio.run(PublicResourceBroker().fetch("https://example.test", "GET"))
    broker = PublicResourceBroker()
    broker.requests = 64
    with pytest.raises(ProbeError, match="64"):
        asyncio.run(broker.fetch("https://example.test", "GET"))


def test_container_has_no_network_mounts_or_host_credentials():
    command = container_command("lumenwatch-browser:test", "fixture")
    for flag in [
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--memory=768m",
        "--memory-swap=768m",
        "--cpus=1",
        "--pids-limit=128",
        "--user=1000:1000",
        "--security-opt=no-new-privileges",
        "--pull=never",
    ]:
        assert flag in command
    assert not any(
        arg.startswith(("--volume", "--mount", "--env", "--privileged")) for arg in command
    )
    with pytest.raises(ProbeError):
        container_command("--privileged bad-image", "fixture")


def test_public_mode_selects_isolated_worker(tmp_path, monkeypatch):
    from app.main import create_app
    from app.service import default_probe_factory

    monkeypatch.setenv("LUMENWATCH_PUBLIC_ORIGIN", "https://monitor.example")
    monkeypatch.setenv("LUMENWATCH_AUTH_TOKEN", "a" * 40)
    monkeypatch.setenv("LUMENWATCH_BROWSER_ENABLED", "true")
    monkeypatch.setenv("LUMENWATCH_ISOLATED_BROWSER_IMAGE", "lumenwatch-browser:test")
    create_app(database_file=tmp_path / "db", capture_path=tmp_path / "captures")
    assert isinstance(
        default_probe_factory({"render_js": True}, tmp_path, True), IsolatedBrowserProbe
    )


@pytest.mark.skipif(os.getenv("RUN_DOCKER_BROWSER_TESTS") != "1", reason="Requires Docker runner")
def test_real_container_renders_js_through_broker(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMENWATCH_ISOLATED_BROWSER_IMAGE", "lumenwatch-browser:test")
    requests = []

    async def resource(_self, url, method):
        requests.append((url, method))
        if url == "https://fixture.example.test/":
            body = (
                b"<html><title>Isolated fixture</title><body>Initial"
                b'<script src="/app.js"></script></body></html>'
            )
            kind = "text/html"
        elif url == "https://fixture.example.test/app.js":
            body = b'document.body.innerText="Rendered inside isolated container"'
            kind = "application/javascript"
        else:
            body, kind = b"", "text/plain"
        return {
            "status": 200,
            "headers": {"content-type": kind},
            "body": base64.b64encode(body).decode(),
        }

    monkeypatch.setattr(PublicResourceBroker, "fetch", resource)
    result = asyncio.run(
        IsolatedBrowserProbe(tmp_path).capture("https://fixture.example.test/", "test")
    )
    assert result.content_text == "Rendered inside isolated container"
    assert result.title == "Isolated fixture"
    assert Path(result.screenshot_path).read_bytes().startswith(b"\x89PNG")
    assert ("https://fixture.example.test/app.js", "GET") in requests


@pytest.mark.skipif(os.getenv("RUN_DOCKER_BROWSER_TESTS") != "1", reason="Requires Docker runner")
def test_real_container_enforces_kernel_boundaries():
    name = "lumenwatch-capture-" + uuid.uuid4().hex
    command = container_command("lumenwatch-browser:test", name)
    command[-1:] = [
        "--entrypoint=python",
        command[-1],
        "-c",
        """
import json,os,socket
from pathlib import Path
result={'uid':os.getuid(), 'memory':Path('/sys/fs/cgroup/memory.max').read_text().strip(),
'cpu':Path('/sys/fs/cgroup/cpu.max').read_text().strip(),
'pids':Path('/sys/fs/cgroup/pids.max').read_text().strip(),
'status':Path('/proc/self/status').read_text()}
try: Path('/worker/forbidden').write_text('x'); result['readonly']=False
except OSError: result['readonly']=True
try: socket.create_connection(('1.1.1.1',443),timeout=1); result['network']=True
except OSError: result['network']=False
print(json.dumps(result))
""",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=20)
        data = json.loads(result.stdout)
        assert data["uid"] == 1000 and data["readonly"] and not data["network"]
        assert data["memory"] == str(768 * 1024 * 1024)
        assert data["pids"] == "128"
        quota, period = map(int, data["cpu"].split())
        assert quota == period
        assert "CapEff:\t0000000000000000" in data["status"]
        assert "NoNewPrivs:\t1" in data["status"]
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10)
