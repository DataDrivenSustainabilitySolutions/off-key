"""CI, image builds and production use one uv release and one Docker Engine release."""

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

    def test_every_ci_swarm_runs_the_production_docker_engine(self):
        role = yaml.safe_load(
            (
                REPOSITORY / "infra/ansible/roles/docker_install/defaults/main.yml"
            ).read_text()
        )
        self.assertRegex(role["docker_engine_version"], r"^\d+\.\d+\.\d+$")
        install = (
            REPOSITORY / "infra/ansible/roles/docker_install/tasks/main.yml"
        ).read_text()
        self.assertIn('"docker-ce=5:{{ docker_engine_version }}-*"', install)
        action = (
            REPOSITORY / ".github/actions/setup-docker-engine/action.yml"
        ).read_text()
        self.assertIn("infra/ansible/roles/docker_install/defaults/main.yml", action)
        jobs = yaml.safe_load((REPOSITORY / ".github/workflows/ci.yml").read_text())[
            "jobs"
        ]
        swarm_jobs = [
            name
            for name, job in jobs.items()
            if any(
                "docker swarm init" in step.get("run", "")
                for step in job.get("steps", [])
            )
        ]
        self.assertTrue(swarm_jobs)
        for name in swarm_jobs:
            with self.subTest(job=name):
                steps = [
                    step.get("uses", step.get("run", ""))
                    for step in jobs[name]["steps"]
                ]
                engine = steps.index("./.github/actions/setup-docker-engine")
                # Nothing may use Docker before the engine is replaced.
                self.assertFalse(any("docker" in step for step in steps[:engine]))


if __name__ == "__main__":
    unittest.main()
