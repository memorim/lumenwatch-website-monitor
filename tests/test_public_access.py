from fastapi.testclient import TestClient
import pytest
from app.main import create_app


def test_public_access_protects_api_and_captures(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMENWATCH_PUBLIC_ORIGIN", "https://monitor.example")
    monkeypatch.setenv("LUMENWATCH_AUTH_TOKEN", "a" * 40)
    app = create_app(database_file=tmp_path/"db", capture_path=tmp_path/"captures")
    with TestClient(app, base_url="https://monitor.example") as client:
        assert client.get("/api/overview").status_code == 401
        assert client.get("/captures/anything.png").status_code == 401
        headers = {"Authorization": "Bearer " + "a" * 40}
        assert client.get("/api/overview", headers=headers).status_code == 200
        assert client.get("/api/overview", headers=headers | {"Host": "evil.example"}).status_code == 403
        assert client.post("/api/targets", headers=headers | {"Origin":"https://evil.example"}, json={}).status_code == 403


def test_public_mode_rejects_missing_credentials_and_browser(tmp_path, monkeypatch):
    monkeypatch.setenv("LUMENWATCH_PUBLIC_ORIGIN", "https://monitor.example")
    with pytest.raises(ValueError):
        create_app(database_file=tmp_path/"db", capture_path=tmp_path/"captures")
    monkeypatch.setenv("LUMENWATCH_AUTH_TOKEN", "a" * 40)
    monkeypatch.setenv("LUMENWATCH_BROWSER_ENABLED", "true")
    with pytest.raises(ValueError, match="isolated"):
        create_app(database_file=tmp_path/"db", capture_path=tmp_path/"captures")
