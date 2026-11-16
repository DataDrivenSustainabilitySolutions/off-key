"""A failed release names its failed tasks publicly, and never their output."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import ROOT, ansible, load_script

with patch.dict(sys.modules, {"check_application": load_script("check_application")}):
    failed = load_script("failed_tasks")
TASK_RESULT = "result-text-that-stays-in-the-private-log"
PLAYBOOK = f"""
- hosts: localhost
  connection: local
  gather_facts: false
  vars:
    ansible_python_interpreter: {sys.executable}
  tasks:
    - name: Tolerate an optional probe
      command: "false"
      ignore_errors: true
    - name: Check every node
      assert:
        that: item != 'second'
        fail_msg: "{TASK_RESULT}"
      loop: [first, second]
    - name: Never reached
      debug:
        msg: unreachable
"""


class FailedTaskTests(unittest.TestCase):
    def test_real_ansible_log_names_only_the_failed_task(self):
        with tempfile.TemporaryDirectory() as directory:
            playbook = Path(directory) / "release.yml"
            playbook.write_text(PLAYBOOK)
            result = ansible("playbook", "-i", "localhost,", playbook, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(TASK_RESULT, result.stdout)
            log = Path(directory) / "release.log"
            log.write_text(result.stdout)
            printed = subprocess.run(
                [sys.executable, ROOT / "scripts/failed_tasks.py", log],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        self.assertEqual(printed, "Failed Ansible task: Check every node\n")

    def test_unreachable_hosts_and_handlers_are_named(self):
        lines = [
            "TASK [stack_deploy : Connect] ******",
            "fatal: [manager]: UNREACHABLE! => changed=false",
            "  msg: ssh failed",
            "RUNNING HANDLER [stack_deploy : Reload] ******",
            "failed: [manager] (item=a) => changed=false",
        ]
        self.assertEqual(
            failed.failed_tasks(lines),
            ["stack_deploy : Connect", "stack_deploy : Reload"],
        )

    def test_a_known_cause_prints_only_its_fixed_description(self):
        lines = [
            "TASK [stack_prepare : Read the currently deployed frontend image] ***",
            "fatal: [manager]: UNREACHABLE! => changed=false",
            (
                "  msg: 'Failed to connect to the host via ssh: deploy@100.64.0.1: "
                "Host key verification failed.'"
            ),
            "  unreachable: true",
            "TASK [Read every image a Swarm service still names] ***",
            "fatal: [manager]: FAILED! => changed=false",
            "  msg: 'Missing sudo password'",
            "TASK [Check something] ***",
            "fatal: [manager]: FAILED! => changed=false",
            "  msg: private detail",
            "TASK [Connect elsewhere] ***",
            "fatal: [worker]: UNREACHABLE! => changed=false",
            "  msg: private detail",
        ]
        self.assertEqual(
            failed.failures(lines),
            [
                (
                    "stack_prepare : Read the currently deployed frontend image",
                    "host unreachable: SSH host key is not in the known hosts",
                ),
                (
                    "Read every image a Swarm service still names",
                    "sudo needs a password",
                ),
                ("Check something", None),
                ("Connect elsewhere", "host unreachable"),
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "release.log"
            log.write_text("\n".join(lines) + "\n")
            printed = subprocess.run(
                [sys.executable, ROOT / "scripts/failed_tasks.py", log],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        self.assertNotIn("100.64.0.1", printed)
        self.assertNotIn("private detail", printed)
        self.assertIn(
            "Failed Ansible task: Check something\n"
            "Failed Ansible task: Connect elsewhere (host unreachable)\n",
            printed,
        )

    def test_only_a_fixed_readiness_check_name_is_printed(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            log = directory / "release.log"
            log.write_text(
                "TASK [stack_deploy : Require application readiness after startup] ***\n"
                "fatal: [manager]: FAILED! => changed=false\n"
            )
            report = directory / "readiness"
            printed = {}
            for name, content in {
                "named": "Failed readiness check: ingress heartbeat\n",
                "private": "Failed readiness check: Lab (source-broker:1883)\n",
                "unprefixed": "ingress heartbeat\n",
                "missing": None,
            }.items():
                report.unlink(missing_ok=True)
                if content is not None:
                    report.write_text(content)
                printed[name] = subprocess.run(
                    [
                        sys.executable,
                        ROOT / "scripts/failed_tasks.py",
                        log,
                        "--readiness",
                        report,
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout
        task = (
            "Failed Ansible task: stack_deploy : "
            "Require application readiness after startup\n"
        )
        self.assertEqual(
            printed["named"], task + "Failed readiness check: ingress heartbeat\n"
        )
        for name in ("private", "unprefixed", "missing"):
            self.assertEqual(printed[name], task, name)


if __name__ == "__main__":
    unittest.main()
