"""Disposable Linux/Docker integration check; never uses production tokens or volumes."""

import base64
import json
import os
import secrets
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def main():
    name = "lumenwatch-check-" + secrets.token_hex(4)
    token = secrets.token_urlsafe(40)
    origin = "https://localhost:8443"
    env = dict(os.environ, LUMENWATCH_PUBLIC_ORIGIN=origin, LUMENWATCH_AUTH_TOKEN=token)
    command = [
        "docker",
        "compose",
        "-p",
        name,
        "-f",
        "deploy/docker-compose.public.yml",
        "-f",
        "deploy/docker-compose.smoke.yml",
    ]

    def compose(*args, capture=False):
        return subprocess.run(
            command + list(args),
            env=env,
            check=True,
            timeout=300,
            capture_output=capture,
            text=True,
        ).stdout

    try:
        compose("up", "--build", "-d", "--wait", "--wait-timeout", "180")
        compose("exec", "-T", "lumenwatch", "docker", "version", "--format", "{{.Client.Version}}")
        with tempfile.TemporaryDirectory(prefix="lumenwatch-ca-") as temporary:
            certificate = Path(temporary) / "root.crt"
            container = compose("ps", "-q", "caddy", capture=True).strip()
            for _attempt in range(30):
                result = subprocess.run(
                    [
                        "docker",
                        "cp",
                        container + ":/data/caddy/pki/authorities/local/root.crt",
                        str(certificate),
                    ],
                    capture_output=True,
                )
                if result.returncode == 0:
                    break
                time.sleep(1)
            context = ssl.create_default_context(cafile=str(certificate))

            def request(method, path, body=None, authorization=None):
                headers = {"Origin": origin, "Content-Type": "application/json"}
                if authorization:
                    headers["Authorization"] = authorization
                req = urllib.request.Request(
                    origin + path,
                    method=method,
                    headers=headers,
                    data=json.dumps(body).encode() if body is not None else None,
                )
                try:
                    with urllib.request.urlopen(req, context=context, timeout=30) as response:
                        data = response.read()
                        return response.status, json.loads(
                            data
                        ) if "application/json" in response.headers.get(
                            "Content-Type", ""
                        ) else data
                except urllib.error.HTTPError as error:
                    return error.code, None

            bearer = "Bearer " + token
            code = 0
            for _attempt in range(30):
                try:
                    code, _ = request("GET", "/api/health", authorization=bearer)
                    if code == 200:
                        break
                except OSError:
                    pass
                time.sleep(1)
            assert code == 200
            assert request("GET", "/api/health")[0] == 401
            basic = "Basic " + base64.b64encode(("operator:" + token).encode()).decode()
            assert request("GET", "/", authorization=basic)[0] == 200
            code, target = request(
                "POST",
                "/api/targets",
                {
                    "name": "Persistent deployment check",
                    "url": "https://example.com",
                    "render_js": False,
                },
                bearer,
            )
            assert code == 201
            identifier = target["id"]
            code, private = request(
                "POST",
                "/api/targets",
                {
                    "name": "Private address check",
                    "url": "http://127.0.0.1:8020",
                    "render_js": False,
                },
                bearer,
            )
            assert code == 201
            assert (
                request("POST", "/api/targets/" + private["id"] + "/run", authorization=bearer)[0]
                == 422
            )
            compose("restart", "lumenwatch")
            for _attempt in range(30):
                try:
                    code, recovered = request(
                        "GET", "/api/targets/" + identifier, authorization=bearer
                    )
                    if code == 200:
                        break
                except OSError:
                    pass
                time.sleep(1)
            assert code == 200 and recovered["id"] == identifier
            print(
                json.dumps({"check": "public-compose-https-operator-persistence", "status": "ok"})
            )
    finally:
        # Only this randomly named, disposable CI project is removed.
        compose("down", "-v", "--remove-orphans")


if __name__ == "__main__":
    main()
