"""Build (or check) the reviewed JSON shipped as immutable Swarm configs.

Run from any directory: python3 infra/scripts/build_grafana_dashboards.py --check
No third-party dependencies; dashboard sources live in infra/grafana/.
"""

import argparse
import json
import sys
from pathlib import Path

INFRA = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(INFRA))

from grafana import access, collection, logs, overview, radar


def documents():
    return {
        name: module.build()
        for name, module in (
            ("overview", overview),
            ("collection", collection),
            ("radar", radar),
            ("access", access),
            ("logs", logs),
        )
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if checked-in JSON differs from its source",
    )
    args = parser.parse_args()
    stale = []
    for name, document in documents().items():
        path = INFRA / "stack" / f"grafana-dashboard-{name}.json"
        content = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
        if args.check:
            if not path.exists() or path.read_text() != content:
                stale.append(path.name)
        else:
            path.write_text(content)
    if stale:
        raise SystemExit("Regenerate Grafana dashboards: " + ", ".join(stale))
    print(
        f"{'Checked' if args.check else 'Built'} {len(documents())} Grafana dashboards"
    )


if __name__ == "__main__":
    main()
