"""Runs only inside the networkless, disposable worker container."""

import asyncio
import base64
import json
import sys

from playwright.async_api import async_playwright


def emit(value):
    print(json.dumps(value), flush=True)


async def main():
    configuration = json.loads(sys.stdin.readline(8192))
    lock = asyncio.Lock()

    async def route_request(route):
        async with lock:
            emit({"kind": "request", "url": route.request.url, "method": route.request.method})
            line = await asyncio.to_thread(sys.stdin.readline, 4 * 1024 * 1024)
            response = json.loads(line)
            await route.fulfill(
                status=response["status"],
                headers=response["headers"],
                body=base64.b64decode(response["body"], validate=True),
            )

    async with asyncio.timeout(32), async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                viewport={"width": 1440, "height": 1000},
                accept_downloads=False,
                service_workers="block",
            )
            await context.route("**/*", route_request)
            await context.route_web_socket("**/*", lambda socket: socket.close())
            page = await context.new_page()
            response = await page.goto(
                configuration["url"],
                wait_until="networkidle",
                timeout=25000,
            )
            title = (await page.title())[:1000]
            text = await page.evaluate("() => (document.body?.innerText || '').slice(0, 120000)")
            screenshot = await page.screenshot(full_page=False, animations="disabled", timeout=5000)
            if len(screenshot) > 2 * 1024 * 1024:
                raise ValueError("Screenshot budget exceeded")
            emit(
                {
                    "kind": "result",
                    "title": title,
                    "text": text,
                    "status": response.status if response else 200,
                    "png": base64.b64encode(screenshot).decode("ascii"),
                }
            )
        finally:
            await browser.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        emit({"kind": "error"})
        sys.exit(1)
