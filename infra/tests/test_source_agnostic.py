"""The application names no source; only the production inventory does."""

import subprocess
import unittest

import yaml
from support import ROOT

PROJECT = ROOT.parent
INVENTORY = "infra/ansible/inventories/prod/"


class SourceAgnosticTests(unittest.TestCase):
    def test_only_the_production_inventory_names_its_source(self):
        source = yaml.safe_load(
            (PROJECT / INVENTORY / "group_vars/all/vars.yml").read_text()
        )["broker_route_name"].lower()
        tracked = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=PROJECT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.split("\0")
        named = []
        for path in filter(None, tracked):
            if path.startswith(INVENTORY):
                continue
            file = PROJECT / path
            if not file.is_file():
                continue
            # The demo inventory shares production's defaults through a link;
            # the file it points at is the production inventory itself.
            if file.is_symlink() and file.resolve().is_relative_to(
                (PROJECT / INVENTORY).resolve()
            ):
                continue
            try:
                text = file.read_text()
            except UnicodeDecodeError:
                continue
            if source in text.lower():
                named.append(path)
        self.assertEqual(named, [], f"Files outside {INVENTORY} name the source")


if __name__ == "__main__":
    unittest.main()
