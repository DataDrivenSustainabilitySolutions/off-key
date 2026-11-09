"""Embed the selected hero photograph for the script-free public landing page."""

import argparse
import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "assets/landing/hero-connected-v9.jpg"
DESTINATION = ROOT / "infra/stack/landing-hero.b64.j2"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    encoded = base64.b64encode(SOURCE.read_bytes()).decode("ascii") + "\n"
    if args.check:
        if not DESTINATION.exists() or DESTINATION.read_text() != encoded:
            parser.exit(
                1,
                "Run python3 assets/landing/export.py to refresh the embedded hero.\n",
            )
        print("Embedded hero matches the selected photograph.")
    else:
        DESTINATION.write_text(encoded, encoding="ascii")
        print("Embedded hero updated.")


if __name__ == "__main__":
    main()
