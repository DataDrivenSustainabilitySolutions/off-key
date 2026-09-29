"""Exercise the production frontend with an API that appears after startup."""

import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def main(image):
    name = f"frontend-startup-{uuid.uuid4().hex[:12]}"
    frontend, api = f"{name}-frontend", f"{name}-api"
    try:
        docker("network", "create", name)
        docker(
            "run",
            "-d",
            "--name",
            frontend,
            "--network",
            name,
            "--publish",
            "127.0.0.1::5173",
            "--env",
            "API_UPSTREAM=api-gateway:8080",
            image,
        )
        address = docker("port", frontend, "5173/tcp")
        started = docker("inspect", "--format", "{{.State.StartedAt}}", frontend)

        def expect(path, status, body=None, data=None):
            deadline = time.monotonic() + 45
            last = None
            while time.monotonic() < deadline:
                try:
                    request = Request(
                        f"http://{address}{path}",
                        data=data,
                        headers={"Authorization": "Bearer frontend-smoke"},
                    )
                    try:
                        response = urlopen(request, timeout=2)
                    except HTTPError as error:
                        response = error
                    with response:
                        text = response.read().decode()
                        last = (response.status, text)
                        if response.status == status and (body is None or body in text):
                            return
                except (URLError, TimeoutError, ConnectionError) as error:
                    last = str(error)
                time.sleep(0.5)
            raise AssertionError(f"{path}: expected {status}, got {last}")

        expect("/login", 200, '<div id="root">')
        expect("/favicon.svg", 200, "<svg")
        expect("/api/v1/probe?sample=1", 502)
        with tempfile.TemporaryDirectory(prefix=name) as directory:
            config = Path(directory) / "api.conf"
            for generation in (1, 2):
                config.write_text(
                    "server { listen 8080; default_type text/plain; "
                    f'return 200 "api-{generation} $request_method '
                    '$request_uri $http_authorization"; }\n'
                )
                docker(
                    "run",
                    "-d",
                    "--name",
                    api,
                    "--network",
                    name,
                    "--network-alias",
                    "api-gateway",
                    "--entrypoint",
                    "nginx",
                    "--mount",
                    f"type=bind,src={config},dst=/etc/nginx/conf.d/default.conf,readonly",
                    image,
                    "-g",
                    "daemon off;",
                )
                expect(
                    "/api/v1/probe?sample=1",
                    200,
                    f"api-{generation} GET /v1/probe?sample=1 Bearer frontend-smoke",
                )
                expect(
                    "/api/v1/probe?sample=1",
                    200,
                    f"api-{generation} POST /v1/probe?sample=1 Bearer frontend-smoke",
                    data=b"{}",
                )
                docker("rm", "-f", api)
                expect("/login", 200, '<div id="root">')
        assert (
            docker("inspect", "--format", "{{.State.StartedAt}}", frontend) == started
        )
        print(
            "Frontend stays up before API discovery and across API replacement; proxy paths and authentication headers are preserved."
        )
    except Exception:
        subprocess.run(["docker", "logs", "--tail", "50", frontend], check=False)
        raise
    finally:
        for args in (("rm", "-f", frontend, api), ("network", "rm", name)):
            subprocess.run(
                ["docker", *args],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


if __name__ == "__main__":
    main(sys.argv[1])
