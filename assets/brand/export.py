"""Export the shared vector mark and selected wordmark into application contexts."""

import argparse
import re
from pathlib import Path
from urllib.parse import quote
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]
BRAND = ROOT / "assets/brand"


def exports() -> dict[Path, str]:
    source = (BRAND / "logo.svg").read_text(encoding="utf-8")
    wordmark = (BRAND / "wordmark.svg").read_text(encoding="utf-8")
    path = ElementTree.fromstring(source).find("{http://www.w3.org/2000/svg}path")
    if path is None:
        raise ValueError("The vector master must contain its mark path")
    geometry = path.attrib["d"]
    adaptive = source.replace(
        "  <path ",
        "  <style>:root{color:#000}@media(prefers-color-scheme:dark)"
        "{:root{color:#fff}}</style>\n  <path ",
    )
    black = source.replace('fill="currentColor"', 'fill="#000"')
    white = source.replace('fill="currentColor"', 'fill="#fff"')
    icon = source.replace(' id="mark"', "").replace(
        ' role="img"', ' aria-hidden="true" focusable="false"'
    )
    output = {
        BRAND / "logo-black.svg": black,
        BRAND / "logo-white.svg": white,
        BRAND / "favicon.svg": adaptive,
        ROOT / "frontend/public/brand/logo.svg": source,
        ROOT / "frontend/public/brand/wordmark.svg": wordmark,
        ROOT / "frontend/public/brand/favicon.svg": adaptive,
        ROOT / "frontend/public/favicon.svg": adaptive,
        ROOT / "docs/assets/brand/logo.svg": adaptive,
        ROOT / "docs/assets/brand/logo-black.svg": black,
        ROOT / "docs/assets/brand/logo-white.svg": white,
        ROOT / "docs/assets/brand/favicon.svg": adaptive,
        ROOT / "docs/overrides/.icons/brand/aberration.svg": icon,
    }
    landing = ROOT / "infra/stack/landing.html.j2"
    template = landing.read_text(encoding="utf-8")
    favicon = quote(adaptive, safe="")
    template, icons = re.subn(
        r'<link rel="icon"[^>]*>',
        f'<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,{favicon}">',
        template,
        count=1,
    )
    template, marks = re.subn(
        r'(<svg class="brand-mark"[^>]*>).*?(</svg>)',
        rf'\g<1><path fill="currentColor" d="{geometry}"/>\g<2>',
        template,
        count=1,
        flags=re.DOTALL,
    )
    if icons != 1 or marks != 1:
        raise ValueError("Expected one public-page favicon and brand-mark SVG")
    output[landing] = template
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail on stale exports")
    args = parser.parse_args()
    stale = []
    for destination, expected in exports().items():
        if destination.exists() and destination.read_text(encoding="utf-8") == expected:
            continue
        stale.append(destination.relative_to(ROOT).as_posix())
        if not args.check:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(expected, encoding="utf-8", newline="\n")
    if args.check and stale:
        print("Regenerate brand assets with: python assets/brand/export.py")
        print("\n".join(stale))
        return 1
    print("Brand assets match the master." if args.check else "Brand assets exported.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
