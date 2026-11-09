"""Private environment migration must not rotate credentials or clobber files."""

import os
import tempfile
import unittest
from pathlib import Path

from support import ROOT, load_script, run

rename = load_script("rename_environment")


class RenameEnvironmentTests(unittest.TestCase):
    def test_identity_values_change_but_credentials_and_comments_survive(self):
        before = (
            "# preserve this note\n"
            "export COMPOSE_PROJECT_NAME='off-key'\n"
            "POSTGRES_DB=off_key\n"
            "RADAR_CHECKPOINT_SECRET=off-key-development-checkpoints\n"
            "OFFKEY_VAULT_PASSWORD='off-key-private-password'\n"
            'SYSTEM_LIVE_CREDENTIALS=\'{"off-key-host":"password"}\'\n'
        )
        after, changed = rename.migrate(before)
        self.assertIn("COMPOSE_PROJECT_NAME='aberration'", after)
        self.assertIn("POSTGRES_DB=aberration", after)
        self.assertIn("RADAR_CHECKPOINT_SECRET=off-key-development-checkpoints", after)
        self.assertIn("ABERRATION_VAULT_PASSWORD='off-key-private-password'", after)
        self.assertIn('SYSTEM_LIVE_CREDENTIALS=\'{"off-key-host":"password"}\'', after)
        self.assertTrue(after.startswith("# preserve this note\n"))
        self.assertEqual(len(changed), 3)
        self.assertEqual(rename.migrate(after), (after, []))

    def test_duplicate_destination_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Duplicate destination"):
            rename.migrate("OFFKEY_VAULT_PASSWORD=a\nABERRATION_VAULT_PASSWORD=b\n")

    def test_multiline_credentials_are_not_reinterpreted_as_assignments(self):
        with self.assertRaisesRegex(ValueError, "Multiline dotenv"):
            rename.migrate("JWT_SECRET='first line\nOFFKEY_SECRET=second line\n'\n")

    def test_cli_is_private_and_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = (Path(directory) / name for name in ("old.env", "new.env"))
            source.write_text("POSTGRES_DB=off_key\nJWT_SECRET=never-print-me\n")
            command = (
                os.sys.executable,
                str(ROOT / "scripts/rename_environment.py"),
                str(source),
                "--output",
                str(output),
            )
            result = run(*command)
            self.assertNotIn("never-print-me", result.stdout + result.stderr)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(run(*command, check=False).returncode, 1)
            self.assertIn("POSTGRES_DB=off_key", source.read_text())
