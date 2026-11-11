"""Render public content without starting the application or its test suites."""

import json
import re
import subprocess
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

PROJECT = Path(__file__).resolve().parents[2]


def main():
    for export in ("assets/brand/export.py", "assets/landing/export.py"):
        subprocess.run([sys.executable, PROJECT / export, "--check"], check=True)
    assets = json.loads((PROJECT / "infra/stack/landing-assets.json").read_text())
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
                images = re.findall(r'<img\b[^>]*src="/assets/([^"]+)"', rendered)
                if images != [asset["file"] for asset in assets]:
                    raise ValueError("Hero photographs do not match the image manifest")
                for asset in assets:
                    data = (PROJECT / "assets/landing" / asset["file"]).read_bytes()
                    if asset["type"] == "image/jpeg":
                        valid = data.startswith(b"\xff\xd8") and data.endswith(
                            b"\xff\xd9"
                        )
                    else:
                        valid = data[:4] == b"RIFF" and data[8:12] == b"WEBP"
                    if not valid:
                        raise ValueError(f"Invalid hero image: {asset['file']}")
    print("Landing HTML, Markdown, agent index and hero assets render correctly.")


if __name__ == "__main__":
    main()
