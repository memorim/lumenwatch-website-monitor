import hashlib

from fastapi.testclient import TestClient

from app.main import create_app
from app.models import CaptureResult
from app.probes import ProbeError


def test_synthetic_change_failure_and_recovery_preserve_history(tmp_path):
    class ControlledProbe:
        content = "Synthetic baseline text"
        fails = False

        async def capture(self, _url, _target_id):
            if self.fails:
                raise ProbeError("Synthetic upstream failure")
            return CaptureResult(
                status_code=200,
                title="Synthetic page",
                content_text=self.content,
                content_hash=hashlib.sha256(self.content.encode()).hexdigest(),
                response_ms=1,
                engine="synthetic",
            )

    probe = ControlledProbe()
    app = create_app(
        database_file=tmp_path / "journey.db",
        capture_path=tmp_path / "captures",
        probe_factory=lambda *_: probe,
    )
    with TestClient(app) as client:
        target = client.post(
            "/api/targets",
            json={
                "name": "Synthetic observer",
                "url": "https://example.com",
                "interval_minutes": 30,
                "render_js": False,
            },
        ).json()["id"]
        assert client.post(f"/api/targets/{target}/run").json()["severity"] == "baseline"
        probe.content = "Synthetic replacement: service unavailable, maintenance required"
        change = client.post(f"/api/targets/{target}/run").json()
        assert change["change_score"] > 0
        assert change["added"] and change["removed"]
        probe.fails = True
        assert client.post(f"/api/targets/{target}/run").status_code == 422
        assert len(client.get(f"/api/runs?target_id={target}").json()) == 2
        probe.fails = False
        assert client.post(f"/api/targets/{target}/run").json()["severity"] == "none"
        assert len(client.get(f"/api/runs?target_id={target}").json()) == 3
