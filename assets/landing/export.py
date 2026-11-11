"""Fingerprint the hero photographs for the script-free public landing page."""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {
    "hero_bridge": ("image/jpeg", ROOT / "assets/landing/hero-bridge-v1.jpg"),
    "hero_pipes": ("image/webp", ROOT / "assets/landing/hero-pipes-v1.webp"),
    "hero_conveyor": ("image/webp", ROOT / "assets/landing/hero-conveyor-v1.webp"),
    "hero_solar": ("image/webp", ROOT / "assets/landing/hero-solar-v2.webp"),
    "hero_cooling": ("image/webp", ROOT / "assets/landing/hero-cooling-bank-v1.webp"),
    "hero_gantry": ("image/webp", ROOT / "assets/landing/hero-robotic-gantry-v1.webp"),
    "hero_cables": (
        "image/webp",
        ROOT / "assets/landing/hero-data-cable-runway-v1.webp",
    ),
    "hero_irrigation": (
        "image/webp",
        ROOT / "assets/landing/hero-irrigation-span-v2.webp",
    ),
}
DESTINATION = ROOT / "infra/stack/landing-assets.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
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
