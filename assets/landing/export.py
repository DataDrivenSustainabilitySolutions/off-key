"""Fingerprint hero photographs and embed the landing page's product screenshots."""

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
PRODUCT_IMAGES = {
    "COMPOSER": (
        "product-composer-v1.webp",
        (
            "Aberration visual composer: pressure, flow and temperature inputs pass "
            "through scaling and two parallel detectors into a detection rule "
            "and evidence output."
        ),
    ),
    "EVIDENCE": (
        "product-evidence-v2.webp",
        (
            "Aberration Reporting: an example cooling-circuit pressure reading, "
            "flagged events and sequential evidence on a shared timeline."
        ),
    ),
}
LANDING_HTML = ROOT / "infra/stack/landing.html.j2"


def product_screenshots(parser, check):
    """Keep the small captures inside the existing versioned HTML config."""
    original = LANDING_HTML.read_text()
    updated = original
    for name, (filename, description) in PRODUCT_IMAGES.items():
        data = (ROOT / "assets/landing" / filename).read_bytes()
        if data[:4] != b"RIFF" or data[8:12] != b"WEBP" or len(data) >= 150_000:
            parser.exit(1, f"Invalid or oversized product screenshot: {filename}\n")
        image = base64.b64encode(data).decode("ascii")
        markup = (
            f"<!-- BEGIN PRODUCT {name} -->\n"
            f'<img class="product-screenshot" src="data:image/webp;base64,{image}" '
            'width="1280" height="720" loading="lazy" decoding="async" '
            f'alt="{description}">\n'
            f"<!-- END PRODUCT {name} -->"
        )
        updated, count = re.subn(
            rf"<!-- BEGIN PRODUCT {name} -->.*?<!-- END PRODUCT {name} -->",
            lambda _, replacement=markup: replacement,
            updated,
            flags=re.DOTALL,
        )
        if count != 1:
            parser.exit(1, f"Expected one product {name.lower()} screenshot slot.\n")
    if check:
        if original != updated:
            parser.exit(
                1, "Run python3 assets/landing/export.py to refresh the screenshots.\n"
            )
    else:
        LANDING_HTML.write_text(updated, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    product_screenshots(parser, args.check)
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
