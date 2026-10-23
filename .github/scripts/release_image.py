"""Print the production release image reference for each named image."""

import json
import sys
from pathlib import Path

RELEASE = (
    Path(__file__).resolve().parents[2]
    / "infra/ansible/inventories/prod/group_vars/all/release.yml"
)


def main(*names: str) -> None:
    images = json.loads(RELEASE.read_text())["release"]["images"]
    for name in names:
        print(images[name])


if __name__ == "__main__":
    main(*sys.argv[1:])
