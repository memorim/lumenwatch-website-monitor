from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from time import perf_counter
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.diff_engine import normalize_text
from app.models import CaptureResult

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
CAPTURE_TIMEOUT = 25


class ProbeError(RuntimeError):
    pass


def validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProbeError("Only absolute HTTP and HTTPS URLs are supported.")
    if parsed.username or parsed.password:
        raise ProbeError("URLs containing credentials are not allowed.")
    return url


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class HttpProbe:
    async def capture(self, url: str, _: str) -> CaptureResult:
        validate_url(url)
        started = perf_counter()
        try:
            async with (
                asyncio.timeout(CAPTURE_TIMEOUT),
                httpx.AsyncClient(
                    follow_redirects=False,
                    timeout=20,
                    headers={
                        "User-Agent": "LumenWatch/1.0 (+website change monitor)",
                        "Accept-Encoding": "identity",
                    },
                ) as client,
            ):
                for redirect in range(6):
                    async with client.stream("GET", url) as response:
                        # HTTPX automatic redirects buffer intermediate bodies; close them unread.
                        if response.has_redirect_location:
                            if redirect == 5:
                                raise ProbeError("The target exceeded five redirects.")
                            url = validate_url(str(response.url.join(response.headers["location"])))
                            continue
                        # ponytail: reject compression to bound memory before HTML parsing;
                        # support compressed targets only with a bounded streaming decoder.
                        if (
                            response.headers.get("content-encoding", "identity").lower()
                            != "identity"
                        ):
                            raise ProbeError("Unsupported response encoding; identity is required.")
                        body = bytearray()
                        async for chunk in response.aiter_raw():
                            if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                                raise ProbeError("The target response exceeds 2 MiB.")
                            body.extend(chunk)
                        text = body.decode(response.encoding or "utf-8", errors="replace")
                        break
        except TimeoutError as error:
            raise ProbeError("The capture deadline was exceeded.") from error
        except httpx.HTTPError as error:
            raise ProbeError("The target could not be reached.") from error

        elapsed_ms = round((perf_counter() - started) * 1000)
        soup = BeautifulSoup(text, "html.parser")
        for node in soup(["script", "style", "noscript", "svg"]):
            node.decompose()
        title = normalize_text(soup.title.get_text()) if soup.title else urlparse(url).netloc
        content_text = normalize_text(soup.get_text(" ", strip=True))[:120_000]
        return CaptureResult(
            status_code=response.status_code,
            title=title,
            content_text=content_text,
            content_hash=_digest(content_text),
            response_ms=elapsed_ms,
            engine="httpx",
        )


class BrowserProbe:
    def __init__(self, capture_directory: Path) -> None:
        self.capture_directory = capture_directory

    async def capture(self, url: str, target_id: str) -> CaptureResult:
        validate_url(url)
        try:
            from playwright.async_api import async_playwright
        except ImportError as error:
            raise ProbeError(
                'Browser mode requires: pip install -e ".[browser]" and playwright install chromium'
            ) from error

        target_directory = self.capture_directory / target_id
        target_directory.mkdir(parents=True, exist_ok=True)
        screenshot = target_directory / "latest.png"
        started = perf_counter()

        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                page = await browser.new_page(viewport={"width": 1440, "height": 1000})
                response = await page.goto(url, wait_until="networkidle", timeout=25_000)
                title = normalize_text(await page.title())
                content_text = normalize_text(await page.locator("body").inner_text())[:120_000]
                await page.screenshot(path=str(screenshot), full_page=True)
                status_code = response.status if response else 0
                await browser.close()
        except Exception as error:
            raise ProbeError(
                "Browser capture failed. Check the target and Chromium install."
            ) from error

        return CaptureResult(
            status_code=status_code,
            title=title,
            content_text=content_text,
            content_hash=_digest(content_text),
            response_ms=round((perf_counter() - started) * 1000),
            engine="playwright",
            screenshot_path=str(screenshot),
        )
