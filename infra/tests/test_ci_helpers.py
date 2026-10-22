"""The CI-only helpers under .github/scripts behave as the workflows rely on."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import ROOT

SCRIPTS = ROOT.parent / ".github/scripts"
RELEASE = ROOT / "ansible/inventories/prod/group_vars/all/release.yml"


def junit(*cases):
    """A JUnit report with one testcase per entry; True marks it skipped."""
    body = "".join(
        f'<testcase classname="c" name="t{index}">'
        + ("<skipped/>" if skipped else "")
        + "</testcase>"
        for index, skipped in enumerate(cases)
    )
    return f"<testsuites><testsuite>{body}</testsuite></testsuites>"


class CiHelperTests(unittest.TestCase):
    def test_release_image_prints_each_named_production_image(self):
        images = json.loads(RELEASE.read_text())["release"]["images"]
        result = subprocess.run(
            [sys.executable, SCRIPTS / "release_image.py", "postgres", "emqx"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(
            result.stdout.splitlines(), [images["postgres"], images["emqx"]]
        )

    def test_release_image_fails_for_an_unknown_image(self):
        result = subprocess.run(
            [sys.executable, SCRIPTS / "release_image.py", "unknown"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_required_test_gate_rejects_empty_and_skipped_reports(self):
        cases = {
            "empty": ((), "lane executed no tests"),
            "skipped": ((False, True), "Skipped required lane tests: c::t1"),
            "executed": ((False, False), None),
        }
        for name, (report, failure) in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "results.xml"
                path.write_text(junit(*report))
                result = subprocess.run(
                    [
                        sys.executable,
                        SCRIPTS / "require_executed_tests.py",
                        path,
                        "lane",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if failure is None:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("Verified 2 lane tests", result.stdout)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(failure, result.stderr)


if __name__ == "__main__":
    unittest.main()
