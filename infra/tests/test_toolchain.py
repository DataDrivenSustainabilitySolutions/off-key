"""CI, image builds and production deploys use one uv release."""

import re
import unittest

import yaml
from support import ROOT

REPOSITORY = ROOT.parent


class ToolchainTests(unittest.TestCase):
    def test_uv_version_is_pinned_once_everywhere(self):
        action = yaml.safe_load(
            (REPOSITORY / ".github/actions/setup-backend/action.yml").read_text()
        )
        setup_uv = next(
            step for step in action["runs"]["steps"] if "setup-uv" in step["uses"]
        )
        expected = setup_uv["with"]["version"]
        dockerfile = (REPOSITORY / "backend/Dockerfile").read_text()
        self.assertEqual(
            re.search(r"ghcr\.io/astral-sh/uv:(\S+)", dockerfile).group(1), expected
        )
        for workflow in sorted((REPOSITORY / ".github/workflows").glob("*.yml")):
            with self.subTest(workflow=workflow.name):
                for job in yaml.safe_load(workflow.read_text())["jobs"].values():
                    for step in job.get("steps", []):
                        if "setup-uv" in step.get("uses", ""):
                            self.assertEqual(step["with"]["version"], expected)


if __name__ == "__main__":
    unittest.main()
