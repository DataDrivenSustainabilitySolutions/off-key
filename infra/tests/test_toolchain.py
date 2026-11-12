"""CI, image builds and production use one uv release and one Docker Engine release."""

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from support import ROOT

REPOSITORY = ROOT.parent


class ToolchainTests(unittest.TestCase):
    def test_ci_image_store_preserves_existing_daemon_configuration(self):
        action = yaml.safe_load(
            (REPOSITORY / ".github/actions/setup-docker-engine/action.yml").read_text()
        )
        script = action["runs"]["steps"][0]["run"]
        configure = script.split("sudo python3 - <<'PYTHON'\n", 1)[1].split(
            "\nPYTHON", 1
        )[0]
        for original in [
            None,
            {"log-driver": "json-file", "features": {"buildkit": True}},
            {"features": {"containerd-snapshotter": True}},
        ]:
            with (
                self.subTest(configuration=original),
                tempfile.TemporaryDirectory() as directory,
            ):
                path = Path(directory) / "docker" / "daemon.json"
                if original is not None:
                    path.parent.mkdir()
                    path.write_text(json.dumps(original))
                # Run the action's actual Python against a disposable config.
                subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        configure.replace('"/etc/docker/daemon.json"', repr(str(path))),
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                saved = json.loads(path.read_text())
                self.assertIs(saved["features"].pop("containerd-snapshotter"), False)
                expected = json.loads(json.dumps(original or {}))
                expected.setdefault("features", {}).pop("containerd-snapshotter", None)
                self.assertEqual(saved, expected)

    def test_ci_engine_restart_after_package_installation(self):
        action = yaml.safe_load(
            (REPOSITORY / ".github/actions/setup-docker-engine/action.yml").read_text()
        )
        script = action["runs"]["steps"][0]["run"]
        # Exercise the install/restart/version check without touching the host.
        # Package hooks have left a working daemon but exhausted its start limit.
        install = script[script.index("sudo DEBIAN_FRONTEND=") :]
        shell = r"""
set -euo pipefail
version=29.0.0
package=5:29.0.0-1
start_limit=0
running=0
sudo() {
    case "$*" in
        DEBIAN_FRONTEND=noninteractive\ apt-get\ install*)
            start_limit=1
            running=1
            ;;
        "systemctl reset-failed docker") start_limit=0 ;;
        "systemctl restart docker")
            running=0
            if (( start_limit )); then
                echo 'start-limit-hit' >&2
                return 1
            fi
            if [[ "$restart_fails" == yes ]]; then
                echo 'daemon failed' >&2
                return 1
            fi
            running=1
            ;;
        *) echo "Unexpected privileged command: $*" >&2; return 99 ;;
    esac
}
docker() {
    (( running )) || return 1
    printf '%s\n' "$reported_version"
}
"""
        for restart_fails, reported_version, succeeds in [
            ("no", "29.0.0", True),
            ("yes", "29.0.0", False),
            ("no", "28.0.0", False),
        ]:
            with self.subTest(restart_fails=restart_fails, version=reported_version):
                result = subprocess.run(
                    [
                        "bash",
                        "-c",
                        shell
                        + f"\nrestart_fails={restart_fails}\nreported_version={reported_version}\n"
                        + install,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(
                    result.returncode == 0, succeeds, result.stdout + result.stderr
                )
                if succeeds:
                    self.assertIn("Docker Engine 29.0.0", result.stdout)
                elif restart_fails == "yes":
                    self.assertIn("daemon failed", result.stderr)
                else:
                    self.assertIn("expected 29.0.0", result.stdout)

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

    def test_ci_image_build_and_swarms_use_the_same_docker_engine(self):
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
        for name in ["images", *swarm_jobs]:
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
