"""Reviewable OpenAPI snapshot: CI fails on schema drift until the change is explicitly reviewed."""

import json
import os
import sys
from pathlib import Path


def main():
    root = Path.cwd()
    sys.path.insert(0, str(root))
    if (root / "manage.py").exists():
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "blog_project.settings")
        import django

        django.setup()
        from blog.api import api

        schema = api.get_openapi_schema()
    else:
        from app.main import app

        schema = app.openapi()
    snapshot = json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    path = root / "docs/OPENAPI_CONTRACT.json"
    if "--record" in sys.argv:
        assert not os.getenv("CI"), "Snapshots must be reviewed locally, not regenerated in CI"
        path.write_text(snapshot, encoding="utf-8")
    else:
        assert path.read_text(encoding="utf-8") == snapshot, (
            "OpenAPI changed. Review compatibility and version before updating "
            "docs/OPENAPI_CONTRACT.json."
        )
    print(json.dumps({"check": "openapi_contract", "paths": len(schema["paths"]), "status": "ok"}))


if __name__ == "__main__":
    main()
