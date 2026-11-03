from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from app.database import Database
from app.diff_engine import compare_snapshots
from app.isolated_browser import IsolatedBrowserProbe
from app.models import CaptureResult
from app.probes import BrowserProbe, HttpProbe, ProbeError


class Probe(Protocol):
    async def capture(self, url: str, target_id: str) -> CaptureResult: ...


ProbeFactory = Callable[[dict, Path, bool], Probe]


class TargetNotFoundError(RuntimeError):
    pass


def default_probe_factory(target: dict, capture_directory: Path, browser_enabled: bool) -> Probe:
    if target["render_js"] and browser_enabled:
        if os.getenv("LUMENWATCH_ISOLATED_BROWSER_IMAGE"):
            return IsolatedBrowserProbe(capture_directory)
        return BrowserProbe(capture_directory)
    return HttpProbe()


class MonitorService:
    def __init__(
        self,
        database: Database,
        capture_directory: Path,
        browser_enabled: bool,
        probe_factory: ProbeFactory = default_probe_factory,
    ) -> None:
        self._capacity = asyncio.Semaphore(2)
        self.database = database
        self.capture_directory = capture_directory
        self.browser_enabled = browser_enabled
        self.probe_factory = probe_factory

    async def run_target(self, target_id: str) -> dict:
        if self._capacity.locked():
            raise ProbeError("Capture capacity exhausted; retry later.")
        async with self._capacity:
            return await self._run_target(target_id)

    async def _run_target(self, target_id: str) -> dict:
        target = self.database.get_target(target_id)
        if not target:
            raise TargetNotFoundError("Watch target was not found.")

        probe = self.probe_factory(target, self.capture_directory, self.browser_enabled)
        result = await probe.capture(target["url"], target_id)
        capture = {
            "status_code": result.status_code,
            "title": result.title,
            "content_text": result.content_text,
            "content_hash": result.content_hash,
            "response_ms": result.response_ms,
            "engine": result.engine,
            "screenshot_path": result.screenshot_path,
        }
        previous = self.database.latest_snapshot(target_id)
        change = compare_snapshots(previous, capture)
        return self.database.save_snapshot(target_id, capture, change)
