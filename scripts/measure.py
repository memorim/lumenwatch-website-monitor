"""Synthetic in-process ASGI measurement; never probes external targets."""

import json
import platform
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    application = create_app(database_file=root / "metrics.db", capture_path=root / "captures")
    with TestClient(application) as client:
        for _ in range(10):
            assert client.get("/api/overview").status_code == 200

        def request(_):
            start = perf_counter()
            response = client.get("/api/overview")
            assert response.status_code == 200
            return (perf_counter() - start) * 1000

        start = perf_counter()
        with ThreadPoolExecutor(max_workers=10) as pool:
            durations = sorted(pool.map(request, range(200)))
        result = {
            "kind": "synthetic-local-asgi",
            "date": datetime.now(UTC).isoformat(),
            "python": platform.python_version(),
            "platform": sys.platform,
            "endpoint": "/api/overview",
            "requests": 200,
            "concurrency": 10,
            "errors": 0,
            "p50_ms": round(durations[99], 2),
            "p95_ms": round(durations[189], 2),
            "elapsed_ms": round((perf_counter() - start) * 1000, 2),
            "limits": (
                "In-process TestClient, temporary SQLite, synthetic seed; "
                "no external probe, TCP or hosted load."
            ),
        }
        Path("docs/SYNTHETIC_METRICS.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(result))
