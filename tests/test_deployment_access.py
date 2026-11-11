import base64

from fastapi.testclient import TestClient

from app import healthcheck
from app.main import create_app


def test_operator_can_open_the_browser_without_exposing_token_in_html(tmp_path, monkeypatch):
    token = "private-test-token-" + "a" * 40
    monkeypatch.setenv("LUMENWATCH_PUBLIC_ORIGIN", "https://monitor.example")
    monkeypatch.setenv("LUMENWATCH_AUTH_TOKEN", token)
    app = create_app(database_file=tmp_path / "db", capture_path=tmp_path / "captures")
    with TestClient(app, base_url="https://monitor.example") as client:
        denied = client.get("/")
        assert denied.status_code == 401 and "Basic" in denied.headers["WWW-Authenticate"]
        client.auth = ("operator", token)
        page = client.get("/")
        assert page.status_code == 200 and token not in page.text
        assert client.get("/api/overview").status_code == 200
        assert client.post("/api/targets", json={}).status_code == 403
        assert (
            client.post(
                "/api/targets", headers={"Origin": "https://evil.example"}, json={}
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/targets", headers={"Origin": "https://monitor.example"}, json={}
            ).status_code
            == 422
        )
        client.auth = ("not-operator", token)
        assert client.get("/").status_code == 401
        malformed = "Basic " + base64.b64encode(b"operator").decode()
        assert client.get("/", headers={"Authorization": malformed}).status_code == 401


def test_container_healthcheck_uses_expected_host_and_private_bearer(monkeypatch):
    monkeypatch.setenv("LUMENWATCH_PUBLIC_ORIGIN", "https://monitor.example:8443")
    monkeypatch.setenv("LUMENWATCH_AUTH_TOKEN", "private-health-token-" + "b" * 40)

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

    def open_request(request, timeout):
        assert request.full_url == "http://127.0.0.1:8020/api/health"
        assert request.get_header("Host") == "monitor.example:8443"
        assert request.get_header("Authorization").startswith("Bearer private-health-token-")
        assert timeout == 3
        return Response()

    monkeypatch.setattr(healthcheck, "urlopen", open_request)
    healthcheck.check()
