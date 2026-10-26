# LumenWatch — Website Change Monitor

Capture page versions and explain text changes between saved snapshots.


![Desktop interface](docs/desktop.png)

<img src="docs/mobile.png" width="320" alt="Mobile interface">

[Short interaction recording](docs/demo.gif)

## Implemented

- HTTP captures, extracted text diffs, snapshot history and change levels.
- Responsive dashboard, REST API, MCP tools and an optional scheduler.
- Optional Playwright capture for JavaScript-rendered pages.

## Stack and architecture

Python, FastAPI, HTTPX, Beautiful Soup, SQLite, optional Playwright and MCP.

## Technical mechanisms and security

- REST and MCP reuse the same service logic and persistence. Browser capture is optional; it is not needed by the basic HTTP path.
- Stored page versions make diffs inspectable. Analysis uses deterministic comparison rules.

## Local setup

Python 3.12.14 (see `.python-version`). Activate the virtual environment before the remaining commands.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -c requirements-lock.txt -e ".[dev]"
uvicorn app.main:app --host 127.0.0.1 --port 8020
```

## Configuration

Use [.env.example](.env.example) for supported configuration and keep secrets outside Git. See [configuration details](docs/TECHNICAL.md) for loading settings and optional services.

## Database and upgrades

The SQLite schema initializes on startup. Database/capture paths are configurable; keep persistent data outside temporary build directories.

## Verification

```bash
python -m pytest -q
python tests/check_contract.py
python tests/check_upgrade.py
python -m pip check
python -m ruff check .
```

Existing HTTP/browser adapters are replaced with fixtures in unit tests; the current suite, Ruff, OpenAPI and previous-version upgrade checks are reproducible locally.

CI installs locked dependencies and runs the configured checks; documentation checks also validate local links/images. Python dependency auditing uses `pip-audit --disable-pip --no-deps --strict -r requirements-lock.txt`. A passing scanner only reports known advisories at the time of the run.

## Limits and next steps

- A single trusted local operator controls targets through REST or stdio MCP. Private and loopback targets are intentionally supported. The HTTP/browser capture path is not an SSRF-hardened public URL service: redirects and browser subresources can reach networks available to the host.
- Keep the API on `127.0.0.1`. Docker Compose publishes only `127.0.0.1:8020`; the container's internal `0.0.0.0` listener is required for that mapping. Do not change the mapping, expose it through a tunnel/reverse proxy, or grant untrusted containers access to its network. There are no public accounts or tenant isolation.
- HTTP capture has a 25-second network deadline, at most five redirects and a 2 MiB body budget before HTML parsing. Compression is refused even if a server ignores `Accept-Encoding: identity`, to avoid decompressing an unbounded body. Such targets return a capture error.
- Browser mode remains opt-in and intended only for trusted pages: page JavaScript, subresources, full-page screenshots and concurrent manual captures have no comprehensive resource sandbox. Keep it disabled for unknown targets. The HTTP limits do not apply to Chromium; public deployment is unsupported.

## Further documentation

[Audit findings and follow-up](docs/AUDIT_2026_10.md) · [Technical reference](docs/TECHNICAL.md) · [Change history](CHANGELOG.md)

[API request/response example](docs/API_EXAMPLE.md)
