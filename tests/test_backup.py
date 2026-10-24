import sqlite3
from contextlib import closing

import pytest

from app.database import Database
from app.demo_data import seed_demo_data


def test_online_backup_restores_targets_and_snapshot_history(tmp_path):
    original = Database(tmp_path / "original.db")
    original.initialize()
    seed_demo_data(original)
    restored = Database(tmp_path / "restored.db")
    with (
        closing(sqlite3.connect(original.path)) as source,
        closing(sqlite3.connect(restored.path)) as target,
    ):
        source.backup(target)
        assert target.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert target.execute("PRAGMA foreign_key_check").fetchall() == []
    assert restored.list_targets() == original.list_targets()
    assert restored.list_snapshots() == original.list_snapshots()
    assert restored.overview() == original.overview()


def test_database_connection_closes_and_failed_write_rolls_back(tmp_path):
    database = Database(tmp_path / "closed.db")
    database.initialize()
    with database._connect() as connection:
        assert connection.execute("SELECT 1").fetchone()[0] == 1
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    with pytest.raises(RuntimeError, match="synthetic failure"):
        with database._connect() as connection:
            connection.execute(
                "INSERT INTO targets VALUES ('test','Test','https://example.com',30,0,1,'2030')"
            )
            raise RuntimeError("synthetic failure")
    assert database.count_targets() == 0
    database.path.unlink()
