"""Render public content without starting the application or its test suites."""

import base64
import re
import subprocess
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

PROJECT = Path(__file__).resolve().parents[2]


def main():
    for export in ("assets/brand/export.py", "assets/landing/export.py"):
        subprocess.run([sys.executable, PROJECT / export, "--check"], check=True)
    environment = Environment(
        loader=FileSystemLoader(PROJECT / "infra/stack"),
        undefined=StrictUndefined,
        autoescape=False,  # Templates explicitly escape HTML; Markdown must not.
    )
    for docs_url in ("https://docs.aberration.app", ""):
        for name in ("landing.html.j2", "landing.md.j2", "landing-llms.txt.j2"):
            rendered = environment.get_template(name).render(
                ingress_base_domain="aberration.app",
                frontend_base_url="https://dashboard.aberration.app",
                docs_base_url=docs_url,
            )
            if "{{" in rendered or "{%" in rendered:
                raise ValueError(f"Unrendered template in {name}")
            if not rendered.strip() or len(rendered.encode()) >= 500_000:
                raise ValueError(f"Empty or oversized Swarm config: {name}")
            if name == "landing.html.j2":
                hero = re.search(r"data:image/jpeg;base64,([^\"]+)", rendered)
                if hero is None:
                    raise ValueError("Missing embedded hero")
                decoded = base64.b64decode("".join(hero[1].split()), validate=True)
                if not decoded.startswith(b"\xff\xd8") or not decoded.endswith(
                    b"\xff\xd9"
                ):
                    raise ValueError("Invalid JPEG hero")
    print("Landing HTML, Markdown, agent index and embedded assets render correctly.")


if __name__ == "__main__":
    main()
