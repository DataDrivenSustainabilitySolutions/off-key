"""The application names no source; only the production inventory does."""

import subprocess
import unittest

import yaml
from support import ROOT

PROJECT = ROOT.parent
INVENTORY = "infra/ansible/inventories/prod/"
# Migration 005 hashes these modules into its ledger checksum, so they keep the
# names of the retired v1 format, as do the tests that exercise that format.
FROZEN_HISTORY = {
    "backend/libs/core/src/off_key_core/db/catalogue_upgrade.py",
    "backend/libs/core/src/off_key_core/db/catalogue_v1.py",
    "backend/libs/core/src/off_key_core/db/catalogue_v1_models.py",
    "backend/tests/support/legacy_catalogue.py",
    "backend/tests/tactic/test_legacy_catalogue.py",
}


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
            if path.startswith(INVENTORY) or path in FROZEN_HISTORY:
                continue
            file = PROJECT / path
            if not file.is_file():
                continue
            try:
                text = file.read_text()
            except UnicodeDecodeError:
                continue
            if source in text.lower():
                named.append(path)
        self.assertEqual(named, [], f"Files outside {INVENTORY} name the source")

    def test_frozen_history_still_exists(self):
        # A retired exemption must leave this list with the file it covered.
        for path in FROZEN_HISTORY:
            with self.subTest(path=path):
                self.assertTrue((PROJECT / path).is_file())


if __name__ == "__main__":
    unittest.main()
