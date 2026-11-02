from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import (
    PROJECT_ROOT,
    browser_enabled,
    capture_directory,
    database_path,
    scheduler_enabled,
    scheduler_tick_seconds,
)
from app.database import Database
from app.demo_data import seed_demo_data
from app.probes import ProbeError
from app.scheduler import MonitorScheduler
from app.schemas import TargetCreate
from app.service import MonitorService, ProbeFactory, TargetNotFoundError, default_probe_factory


def create_app(
    database_file: Path | None = None,
    capture_path: Path | None = None,
    probe_factory: ProbeFactory = default_probe_factory,
) -> FastAPI:
    public_origin = os.getenv("LUMENWATCH_PUBLIC_ORIGIN", "")
    auth_token = os.getenv("LUMENWATCH_AUTH_TOKEN", "")
    if public_origin:
        origin = urlparse(public_origin)
        if (
            origin.scheme != "https"
            or not origin.netloc
            or origin.path not in {"", "/"}
            or origin.query
            or origin.fragment
            or origin.username
        ):
            raise ValueError("LUMENWATCH_PUBLIC_ORIGIN must be an HTTPS origin")
        if len(auth_token) < 32:
            raise ValueError(
                "Public access requires LUMENWATCH_AUTH_TOKEN of at least 32 characters"
            )
        if browser_enabled():
            raise ValueError(
                "Public browser capture requires an isolated worker; disable browser mode"
            )
    database = Database(database_file or database_path())
    resolved_capture_path = capture_path or capture_directory()
    resolved_capture_path.mkdir(parents=True, exist_ok=True)
    service = MonitorService(
        database=database,
        capture_directory=resolved_capture_path,
        browser_enabled=browser_enabled(),
        probe_factory=probe_factory,
    )
    scheduler = MonitorScheduler(database, service, tick_seconds=scheduler_tick_seconds())
    scheduler_is_enabled = scheduler_enabled()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.initialize()
        seed_demo_data(database)
        if scheduler_is_enabled:
            await scheduler.start()
        yield
        await scheduler.stop()

    application = FastAPI(
        title="LumenWatch Agent",
        version="0.2.0",
        description="Website change intelligence through REST and MCP.",
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def access_boundary(request, call_next):
        if public_origin:
            if request.headers.get("host") != origin.netloc:
                return JSONResponse({"detail": "Host not allowed"}, status_code=403)
            if not hmac.compare_digest(
                request.headers.get("authorization", "").encode(), ("Bearer " + auth_token).encode()
            ):
                return JSONResponse({"detail": "Authentication required"}, status_code=401)
            if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get(
                "origin", public_origin.rstrip("/")
            ) != public_origin.rstrip("/"):
                return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    application.state.database = database
    application.state.monitor_service = service
    application.state.scheduler = scheduler
    static_directory = PROJECT_ROOT / "app" / "static"
    application.mount("/static", StaticFiles(directory=static_directory), name="static")
    application.mount(
        "/captures",
        StaticFiles(directory=resolved_capture_path),
        name="captures",
    )

    @application.get("/", include_in_schema=False)
    async def dashboard() -> FileResponse:
        return FileResponse(static_directory / "index.html")

    @application.get("/api/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "lumenwatch-agent"}

    @application.get("/api/scheduler", tags=["system"])
    async def scheduler_status() -> dict[str, bool | int]:
        return {
            "enabled": scheduler_is_enabled,
            "running": scheduler.running,
            "tick_seconds": scheduler.tick_seconds,
        }

    @application.get("/api/overview", tags=["monitoring"])
    async def overview() -> dict:
        return database.overview()

    @application.get("/api/targets", tags=["targets"])
    async def list_targets() -> list[dict]:
        return database.list_targets()

    @application.get("/api/targets/{target_id}", tags=["targets"])
    async def get_target(target_id: str) -> dict:
        target = database.get_target(target_id)
        if not target:
            raise HTTPException(status_code=404, detail="Watch target not found.")
        target["snapshots"] = database.list_snapshots(limit=20, target_id=target_id)
        return target

    @application.post("/api/targets", status_code=201, tags=["targets"])
    async def create_target(payload: TargetCreate) -> dict:
        return database.create_target(
            name=payload.name.strip(),
            url=payload.url,
            interval_minutes=payload.interval_minutes,
            render_js=payload.render_js,
        )

    @application.post("/api/targets/{target_id}/run", status_code=201, tags=["monitoring"])
    async def run_target(target_id: str) -> dict:
        try:
            return await service.run_target(target_id)
        except TargetNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ProbeError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.get("/api/runs", tags=["monitoring"])
    async def list_runs(limit: int = 50, target_id: str | None = None) -> list[dict]:
        return database.list_snapshots(
            limit=max(1, min(limit, 200)),
            target_id=target_id,
        )

    @application.get("/api/changes", tags=["monitoring"])
    async def list_changes(limit: int = 50) -> list[dict]:
        return database.list_snapshots(
            limit=max(1, min(limit, 200)),
            changes_only=True,
        )

    @application.get("/api/runs/{snapshot_id}", tags=["monitoring"])
    async def get_run(snapshot_id: str) -> dict:
        snapshot = database.get_snapshot(snapshot_id)
        if not snapshot:
            raise HTTPException(status_code=404, detail="Snapshot not found.")
        return snapshot

    return application


app = create_app()
