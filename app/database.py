from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS targets (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    url TEXT NOT NULL,
                    interval_minutes INTEGER NOT NULL,
                    render_js INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS snapshots (
                    id TEXT PRIMARY KEY,
                    target_id TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    content_text TEXT NOT NULL,
                    response_ms INTEGER NOT NULL,
                    engine TEXT NOT NULL,
                    screenshot_path TEXT,
                    similarity REAL NOT NULL,
                    change_score REAL NOT NULL,
                    severity TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    added_json TEXT NOT NULL,
                    removed_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(target_id) REFERENCES targets(id) ON DELETE CASCADE
                );
                """
            )

    def count_targets(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM targets").fetchone()
        return int(row["count"])

    def create_target(
        self,
        name: str,
        url: str,
        interval_minutes: int,
        render_js: bool,
    ) -> dict[str, Any]:
        target = {
            "id": uuid4().hex[:12],
            "name": name,
            "url": url,
            "interval_minutes": interval_minutes,
            "render_js": int(render_js),
            "enabled": 1,
            "created_at": datetime.now(UTC).isoformat(),
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO targets (
                    id, name, url, interval_minutes, render_js, enabled, created_at
                ) VALUES (
                    :id, :name, :url, :interval_minutes, :render_js, :enabled, :created_at
                )
                """,
                target,
            )
        return self.get_target(target["id"]) or {}

    def list_targets(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM targets ORDER BY created_at DESC").fetchall()

        targets: list[dict[str, Any]] = []
        for row in rows:
            target = self._target_from_row(row)
            target["latest_snapshot"] = self.latest_snapshot(target["id"])
            targets.append(target)
        return targets

    def get_target(self, target_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM targets WHERE id = ?",
                (target_id,),
            ).fetchone()
        return self._target_from_row(row) if row else None

    def save_snapshot(
        self,
        target_id: str,
        capture: dict[str, Any],
        change: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot = {
            "id": uuid4().hex[:12],
            "target_id": target_id,
            "status_code": capture["status_code"],
            "title": capture["title"],
            "content_hash": capture["content_hash"],
            "content_text": capture["content_text"],
            "response_ms": capture["response_ms"],
            "engine": capture["engine"],
            "screenshot_path": capture.get("screenshot_path"),
            "similarity": change["similarity"],
            "change_score": change["change_score"],
            "severity": change["severity"],
            "summary": change["summary"],
            "added_json": json.dumps(change["added"], ensure_ascii=False),
            "removed_json": json.dumps(change["removed"], ensure_ascii=False),
            "created_at": datetime.now(UTC).isoformat(),
        }
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO snapshots (
                    id, target_id, status_code, title, content_hash, content_text,
                    response_ms, engine, screenshot_path, similarity, change_score,
                    severity, summary, added_json, removed_json, created_at
                ) VALUES (
                    :id, :target_id, :status_code, :title, :content_hash, :content_text,
                    :response_ms, :engine, :screenshot_path, :similarity, :change_score,
                    :severity, :summary, :added_json, :removed_json, :created_at
                )
                """,
                snapshot,
            )
        return self.get_snapshot(snapshot["id"]) or {}

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT snapshots.*, targets.name AS target_name, targets.url AS target_url
                FROM snapshots
                JOIN targets ON targets.id = snapshots.target_id
                WHERE snapshots.id = ?
                """,
                (snapshot_id,),
            ).fetchone()
        return self._snapshot_from_row(row) if row else None

    def latest_snapshot(self, target_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT snapshots.*, targets.name AS target_name, targets.url AS target_url
                FROM snapshots
                JOIN targets ON targets.id = snapshots.target_id
                WHERE target_id = ?
                ORDER BY snapshots.created_at DESC
                LIMIT 1
                """,
                (target_id,),
            ).fetchone()
        return self._snapshot_from_row(row) if row else None

    def list_snapshots(
        self,
        limit: int = 50,
        target_id: str | None = None,
        changes_only: bool = False,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if target_id:
            clauses.append("snapshots.target_id = ?")
            parameters.append(target_id)
        if changes_only:
            clauses.append("snapshots.severity NOT IN ('none', 'baseline')")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(limit)

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT snapshots.*, targets.name AS target_name, targets.url AS target_url
                FROM snapshots
                JOIN targets ON targets.id = snapshots.target_id
                {where}
                ORDER BY snapshots.created_at DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [self._snapshot_from_row(row) for row in rows]

    def overview(self) -> dict[str, float | int]:
        with self._connect() as connection:
            target_row = connection.execute(
                """
                SELECT COUNT(*) AS total, COALESCE(SUM(enabled), 0) AS active
                FROM targets
                """
            ).fetchone()
            snapshot_row = connection.execute(
                """
                SELECT
                    COUNT(*) AS checks,
                    COALESCE(AVG(response_ms), 0) AS average_response_ms,
                    COALESCE(SUM(
                        CASE WHEN severity NOT IN ('none', 'baseline') THEN 1 ELSE 0 END
                    ), 0) AS changes
                FROM snapshots
                """
            ).fetchone()
        return {
            "targets": int(target_row["total"]),
            "active_targets": int(target_row["active"]),
            "checks": int(snapshot_row["checks"]),
            "changes": int(snapshot_row["changes"]),
            "average_response_ms": round(float(snapshot_row["average_response_ms"]), 1),
        }

    @staticmethod
    def _target_from_row(row: sqlite3.Row) -> dict[str, Any]:
        target = dict(row)
        target["render_js"] = bool(target["render_js"])
        target["enabled"] = bool(target["enabled"])
        return target

    @staticmethod
    def _snapshot_from_row(row: sqlite3.Row) -> dict[str, Any]:
        snapshot = dict(row)
        snapshot["added"] = json.loads(snapshot.pop("added_json"))
        snapshot["removed"] = json.loads(snapshot.pop("removed_json"))
        return snapshot
