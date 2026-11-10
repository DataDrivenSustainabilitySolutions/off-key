"""Embed the hero photographs for the script-free public landing page."""

import argparse
import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {
    "hero_bridge": ROOT / "assets/landing/hero-bridge-v1.jpg",
    "hero_pipes": ROOT / "assets/landing/hero-pipes-v1.jpg",
}
DESTINATION = ROOT / "infra/stack/landing-hero.b64.j2"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    encoded = "".join(
        "{% set " + name + " = 'data:image/jpeg;base64,"
        + base64.b64encode(source.read_bytes()).decode("ascii")
        + "' %}\n"
        for name, source in SOURCES.items()
    )
    if args.check:
        if not DESTINATION.exists() or DESTINATION.read_text() != encoded:
            parser.exit(
                1,
                "Run python3 assets/landing/export.py to refresh the embedded hero.\n",
            )
        print("Embedded heroes match the selected photographs.")
    else:
        DESTINATION.write_text(encoded, encoding="ascii")
        print("Embedded hero updated.")


if __name__ == "__main__":
    main()
