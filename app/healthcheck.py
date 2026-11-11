"""Private container readiness check using the same access boundary as public callers."""

import os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def check():
    origin = os.getenv("LUMENWATCH_PUBLIC_ORIGIN", "")
    headers = {}
    if origin:
        headers["Host"] = urlsplit(origin).netloc
        headers["Authorization"] = "Bearer " + os.environ["LUMENWATCH_AUTH_TOKEN"]
    request = Request("http://127.0.0.1:8020/api/health", headers=headers)
    with urlopen(request, timeout=3) as response:
        if response.status != 200:
            raise RuntimeError("Service is not ready")


if __name__ == "__main__":
    try:
        check()
    except Exception:
        raise SystemExit(1) from None
