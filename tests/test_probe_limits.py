import asyncio
from pathlib import Path

import httpx
import pytest

from app import probes


class FixtureStream(httpx.AsyncByteStream):
    def __init__(self, chunks, delay=0):
        self.chunks = chunks
        self.delay = delay
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            await asyncio.sleep(self.delay)
            yield chunk

    async def aclose(self):
        self.closed = True


def install_transport(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr(
        probes.httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs),
    )


def test_small_page_and_redirect_remain_supported(monkeypatch):
    def handler(request):
        assert request.headers["accept-encoding"] == "identity"
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "/page"})
        return httpx.Response(200, stream=FixtureStream([b"<title>Example</title><p>Hello</p>"]))

    install_transport(monkeypatch, handler)
    result = asyncio.run(probes.HttpProbe().capture("http://localhost/start", "fixture"))
    assert result.title == "Example"
    assert "Hello" in result.content_text


def test_oversized_body_is_rejected_and_stream_is_closed(monkeypatch):
    stream = FixtureStream([b"x" * (2 * 1024 * 1024), b"x"])
    install_transport(monkeypatch, lambda _: httpx.Response(200, stream=stream))
    with pytest.raises(probes.ProbeError, match="2 MiB"):
        asyncio.run(probes.HttpProbe().capture("http://localhost/large", "fixture"))
    assert stream.closed


def test_compressed_response_cannot_bypass_byte_budget(monkeypatch):
    install_transport(
        monkeypatch,
        lambda _: httpx.Response(
            200, headers={"Content-Encoding": "gzip"}, stream=FixtureStream([b"unused"])
        ),
    )
    with pytest.raises(probes.ProbeError, match="encoding"):
        asyncio.run(probes.HttpProbe().capture("http://localhost/compressed", "fixture"))


def test_total_deadline_stops_a_slow_stream(monkeypatch):
    stream = FixtureStream([b"x"] * 100, delay=0.002)
    install_transport(monkeypatch, lambda _: httpx.Response(200, stream=stream))
    monkeypatch.setattr(probes, "CAPTURE_TIMEOUT", 0.01, raising=False)
    with pytest.raises(probes.ProbeError, match="deadline"):
        asyncio.run(probes.HttpProbe().capture("http://localhost/slow", "fixture"))
    assert stream.closed


def test_redirect_chain_is_bounded(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request.url)
        return httpx.Response(302, headers={"Location": "/again"})

    install_transport(monkeypatch, handler)
    with pytest.raises(probes.ProbeError):
        asyncio.run(probes.HttpProbe().capture("http://localhost/again", "fixture"))
    assert len(requests) <= 6


def test_intermediate_redirect_body_is_never_buffered(monkeypatch):
    class UnreadRedirect(FixtureStream):
        async def __aiter__(self):
            raise AssertionError("An intermediate response body was consumed")
            yield b""  # pragma: no cover - retain the async iterator protocol

    stream = UnreadRedirect([])

    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "/page"}, stream=stream)
        return httpx.Response(200, stream=FixtureStream([b"<p>Final page</p>"]))

    install_transport(monkeypatch, handler)
    result = asyncio.run(probes.HttpProbe().capture("http://localhost/start", "fixture"))
    assert result.content_text == "Final page"
    assert stream.closed


def test_compose_does_not_publish_the_unauthenticated_api_to_the_lan():
    compose = (Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text()
    assert '"127.0.0.1:8020:8020"' in compose
    assert '"8020:8020"' not in compose
