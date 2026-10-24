"""Upgrade an isolated database built by an immutable previous release, preserving its records."""

import io
import json
import os
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from contextlib import closing
from pathlib import Path


def snapshot(path):
    with closing(sqlite3.connect(path)) as db:
        tables = db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        result = []
        for (name,) in tables:
            if name in {"alembic_version", "django_migrations"}:
                continue

            def quote(value):
                return '"' + value.replace('"', '""') + '"'

            columns = [row[1] for row in db.execute("PRAGMA table_info(" + quote(name) + ")")]
            rows = db.execute(
                "SELECT " + ",".join(map(quote, columns)) + " FROM " + quote(name)
            ).fetchall()
            result.append((name, columns, set(rows)))
        return result


def main():
    root = Path.cwd()
    baseline = json.loads((root / "tests/upgrade-baseline.json").read_text())
    commit, kind = baseline["commit"], baseline["kind"]
    assert len(commit) == 40 and all(c in "0123456789abcdef" for c in commit)
    if subprocess.run(
        ["git", "cat-file", "-e", commit], capture_output=True, check=False
    ).returncode:
        subprocess.run(["git", "fetch", "--depth=1", "origin", commit], check=True)
    env = os.environ.copy()
    env["DJANGO_DEBUG"] = "1"
    for key in list(env):
        if key.startswith("POSTGRES_"):
            del env[key]
    with tempfile.TemporaryDirectory(prefix="portfolio-upgrade-") as temporary:
        old = Path(temporary) / "previous"
        old.mkdir()
        archive = subprocess.check_output(["git", "archive", "--format=tar", commit])
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(old, filter="data")
        database = Path(temporary) / "records.sqlite"
        env["DATABASE_URL"] = "sqlite:///" + database.as_posix()

        def python(cwd, code):
            subprocess.run(
                [sys.executable, "-c", code, str(database)], cwd=cwd, env=env, check=True
            )

        if kind == "approval":
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=old, env=env, check=True
            )
            python(
                old,
                (
                    "from app.database import SessionLocal;"
                    "from app.models import OutboxEvent;"
                    "db=SessionLocal();"
                    "db.add(OutboxEvent(workspace_id='upgrade',request_id='record',event_type='created',payload={'preserve':'value'}));"
                    "db.commit();"
                    "db.close()"
                ),
            )
        elif kind == "django":
            prepare = (
                "import os,sys;"
                "os.environ['DJANGO_SETTINGS_MODULE']='blog_project.settings';"
                "from django.conf import settings;"
                "settings.DATABASES['default']['NAME']=sys.argv[1];"
                "import django;"
                "django.setup();"
                "from django.core.management import call_command;"
                "call_command('migrate',interactive=False,verbosity=0);"
            )
            python(
                old,
                prepare
                + (
                    "from django.contrib.auth import get_user_model;"
                    "from blog.models import Category,Article;"
                    "u=get_user_model().objects.create_user(username='upgrade-marker',password='only-local-fixture');"
                    "c=Category.objects.create(name='Upgrade',slug='upgrade');"
                    "Article.objects.create(author=u,category=c,title='Upgrade',content='Keep')"
                ),
            )
        elif kind == "lumen":
            python(
                old,
                (
                    "import sys;"
                    "from pathlib import Path;"
                    "from app.database import Database;"
                    "db=Database(Path(sys.argv[1]));"
                    "db.initialize();"
                    "db.create_target('Upgrade marker','https://memorim.github.io/',60,False)"
                ),
            )
        else:
            python(
                old,
                (
                    "import sys;"
                    "from pathlib import Path;"
                    "from app.database import Database;"
                    "db=Database(Path(sys.argv[1]));"
                    "db.initialize();"
                    "db.save_action_item('memorim/project','Preserve this action','medium')"
                ),
            )
        before = snapshot(database)
        assert any(rows for _, _, rows in before)
        if kind == "approval":
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root, env=env, check=True
            )
        elif kind == "django":
            python(root, prepare)
        else:
            python(
                root,
                (
                    "import sys;"
                    "from pathlib import Path;"
                    "from app.database import Database;"
                    "Database(Path(sys.argv[1])).initialize()"
                ),
            )
        after = {name: (columns, rows) for name, columns, rows in snapshot(database)}
        for name, columns, rows in before:
            new_columns, new_rows = after[name]
            projected = {
                tuple(row[new_columns.index(column)] for column in columns) for row in new_rows
            }
            assert rows <= projected, "Records changed in " + name
        with closing(sqlite3.connect(database)) as db:
            assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        print(
            json.dumps(
                {
                    "check": "previous_release_upgrade",
                    "from": commit,
                    "tables": len(before),
                    "records": sum(len(rows) for _, _, rows in before),
                    "status": "ok",
                }
            )
        )


if __name__ == "__main__":
    main()
