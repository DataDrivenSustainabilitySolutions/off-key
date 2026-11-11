"""Fingerprint hero photographs and embed the landing page's product screenshot."""

import argparse
import base64
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {
    "hero_bridge": ("image/jpeg", ROOT / "assets/landing/hero-bridge-v1.jpg"),
    "hero_cables": (
        "image/webp",
        ROOT / "assets/landing/hero-data-cable-runway-v1.webp",
    ),
    "hero_pipes": ("image/webp", ROOT / "assets/landing/hero-pipes-v1.webp"),
    "hero_conveyor": ("image/webp", ROOT / "assets/landing/hero-conveyor-v1.webp"),
    "hero_solar": ("image/webp", ROOT / "assets/landing/hero-solar-v2.webp"),
    "hero_cooling": ("image/webp", ROOT / "assets/landing/hero-cooling-bank-v1.webp"),
    "hero_gantry": ("image/webp", ROOT / "assets/landing/hero-robotic-gantry-v1.webp"),
    "hero_irrigation": (
        "image/webp",
        ROOT / "assets/landing/hero-irrigation-span-v2.webp",
    ),
}
DESTINATION = ROOT / "infra/stack/landing-assets.json"
PRODUCT_IMAGE = ROOT / "assets/landing/product-evidence-v1.webp"
LANDING_HTML = ROOT / "infra/stack/landing.html.j2"


def product_screenshot(parser, check):
    """Keep the small screenshot inside the existing versioned HTML config."""
    data = PRODUCT_IMAGE.read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP" or len(data) >= 200_000:
        parser.exit(1, "Invalid or oversized product screenshot.\n")
    image = base64.b64encode(data).decode("ascii")
    markup = (
        "<!-- BEGIN PRODUCT SCREENSHOT -->\n"
        f'<img class="product-screenshot" src="data:image/webp;base64,{image}" '
        'width="1440" height="1000" loading="lazy" decoding="async" '
        'alt="Aberration Reporting: outlet pressure and its detection evidence '
        'on a shared timeline, with an example change marked in the reading.">\n'
        "<!-- END PRODUCT SCREENSHOT -->"
    )
    original = LANDING_HTML.read_text()
    updated, count = re.subn(
        r"<!-- BEGIN PRODUCT SCREENSHOT -->.*?<!-- END PRODUCT SCREENSHOT -->",
        lambda _: markup,
        original,
        flags=re.DOTALL,
    )
    if count != 1:
        parser.exit(1, "Expected one product screenshot slot in the landing page.\n")
    if check:
        if original != updated:
            parser.exit(
                1, "Run python3 assets/landing/export.py to refresh the screenshot.\n"
            )
    else:
        LANDING_HTML.write_text(updated, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    product_screenshot(parser, args.check)
    assets = []
    for name, (mime_type, source) in SOURCES.items():
        data = source.read_bytes()
        if not data or len(data) >= 500_000:
            parser.exit(1, f"Empty or oversized Swarm image config: {source}\n")
        assets.append(
            {
                "name": name,
                "file": source.name,
                "type": mime_type,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    encoded = json.dumps(assets, indent=2) + "\n"
    if args.check:
        if not DESTINATION.exists() or DESTINATION.read_text() != encoded:
            parser.exit(
                1,
                "Run python3 assets/landing/export.py to refresh the image manifest.\n",
            )
        print("Hero image manifest matches the selected photographs.")
    else:
        DESTINATION.write_text(encoded, encoding="ascii")
        print("Hero image manifest updated.")


if __name__ == "__main__":
    main()
