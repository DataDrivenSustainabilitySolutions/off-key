"""Probe the real docs server, including nested pages and machine-readable exports."""

import re
import subprocess
import sys
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


def main(image):
    name = f"docs-smoke-{uuid.uuid4().hex[:12]}"
    opener = build_opener(NoRedirect())
    try:
        docker("run", "-d", "--name", name, "-p", "127.0.0.1::80", image)
        address = docker("port", name, "80/tcp")

        def fetch(path):
            request = Request(
                f"http://{address}{path}", headers={"Host": "docs.aberration.app"}
            )
            try:
                response = opener.open(request, timeout=3)
            except HTTPError as error:
                response = error
            with response:
                return response.status, response.headers, response.read().decode()

        deadline = time.monotonic() + 30
        while True:
            try:
                status, _, home = fetch("/")
                assert status == 200, status
                break
            except (URLError, TimeoutError, ConnectionError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.5)

        for path, mime, text in (
            ("/", "text/html", "https://docs.aberration.app/"),
            ("/getting-started/", "text/html", "Getting started"),
            ("/operations/production/", "text/html", "Production releases"),
            ("/getting-started.md", "text/markdown", "# Getting started"),
            (
                "/llms.txt",
                "text/plain",
                "https://docs.aberration.app/getting-started.md",
            ),
            ("/llms-full.txt", "text/plain", "# Getting started"),
        ):
            status, headers, body = fetch(path)
            assert status == 200, (path, status)
            assert mime in headers["Content-Type"], (path, headers)
            assert text in body, (path, text)
        assets = set(
            re.findall(r'(?:href|src)="((?:\./)?assets/[^"?]+\.(?:css|js))', home)
        )
        assert assets, "No local CSS or JavaScript found in the built homepage"
        for asset in assets:
            status, _, _ = fetch("/" + asset.removeprefix("./"))
            assert status == 200, (asset, status)
        status, headers, _ = fetch("/getting-started")
        assert status == 301, status
        assert headers["Location"] == "/getting-started/", headers
        assert fetch("/nonexistent-docs-smoke-page/")[0] == 404
        print(
            "Documentation pages, local assets, Markdown exports, redirects and 404s passed."
        )
    except Exception:
        subprocess.run(["docker", "logs", "--tail", "30", name], check=False)
        raise
    finally:
        subprocess.run(
            ["docker", "rm", "-f", name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


if __name__ == "__main__":
    main(sys.argv[1])
