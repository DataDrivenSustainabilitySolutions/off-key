"""A release reports where its time went publicly, and never task output."""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from support import ROOT, ansible, load_script

timings = load_script("task_timings")
TASK_RESULT = "result-text-that-stays-in-the-private-log"
PLAYBOOK = f"""
- hosts: localhost
  connection: local
  gather_facts: false
  vars:
    ansible_python_interpreter: {sys.executable}
    service: tactic
  tasks:
    - name: "{{{{ service }}}} | wait for the slow step"
      command: sleep 1.2
    - name: Report a private value
      debug:
        msg: "{TASK_RESULT}"
    - name: Check the release
      assert:
        that: false
        fail_msg: "{TASK_RESULT}"
"""


class TaskTimingTests(unittest.TestCase):
    def test_real_ansible_log_reports_only_names_and_durations(self):
        with tempfile.TemporaryDirectory() as directory:
            playbook = Path(directory) / "release.yml"
            playbook.write_text(PLAYBOOK)
            result = ansible(
                "playbook",
                "-i",
                "localhost,",
                playbook,
                env=os.environ
                | {"ANSIBLE_CALLBACKS_ENABLED": "ansible.posix.profile_tasks"},
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(TASK_RESULT, result.stdout)
            log = Path(directory) / "release.log"
            log.write_text(result.stdout)
            printed = {
                script: subprocess.run(
                    [sys.executable, ROOT / f"scripts/{script}.py", log],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout
                for script in ("task_timings", "failed_tasks")
            }
        report = printed["task_timings"].splitlines()
        self.assertRegex(report[0], r"^Ansible ran 3 tasks in \d+m\d\ds; median ")
        self.assertEqual(report[1], "Slowest Ansible tasks:")
        # A busy runner stretches the sleep but never shortens it.
        slowest = re.fullmatch(
            r" +(?P<seconds>\d+\.\d)s  tactic \| wait for the slow step", report[2]
        )
        self.assertIsNotNone(slowest)
        self.assertGreaterEqual(float(slowest["seconds"]), 1.2)
        self.assertEqual(len(report), 5)
        self.assertNotIn(TASK_RESULT, printed["task_timings"])
        # The timing stamps leave failed-task reporting unchanged.
        self.assertEqual(
            printed["failed_tasks"], "Failed Ansible task: Check the release\n"
        )

    def test_each_rehearsal_deployment_adds_its_timings_to_the_lane_report(self):
        import swarm_smoke

        log = [
            "TASK [Connect] ****",
            "Monday 09 November 2026  21:16:00 +0000 (0:00:00.050)       0:00:00.050 *****",
            "TASK [stack_deploy : Wait for all stack services to converge] ****",
            "Monday 09 November 2026  21:16:03 +0000 (0:00:03.000)       0:00:03.050 *****",
            "TASK [Finish] ****",
            "Monday 09 November 2026  21:16:48 +0000 (0:00:45.000)       0:00:48.050 *****",
            "TASKS RECAP ****",
            "stack_deploy : Wait for all stack services to converge ------------- 45.00s",
            "Connect ------------------------------------------------------------- 3.00s",
        ]
        commands = []

        def run(*args, **kwargs):
            commands.append(kwargs)
            return SimpleNamespace(stdout="\n".join(log))

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "inputs.json").write_text("{}")
            (directory / "stack").mkdir()
            (directory / "stack/validation.json").write_text(
                '{"deployment_secret_names": {}}'
            )
            with patch.object(swarm_smoke, "run", side_effect=run):
                swarm_smoke.report(directory, "Initial deployment")
                swarm_smoke.deploy(directory, "apply")
                swarm_smoke.deploy(directory, "verify")
            report = (directory / swarm_smoke.TIMINGS).read_text().splitlines()
        for command in commands:
            # The same callback as the production deployment, with the usual settings.
            self.assertEqual(
                command["env"]["ANSIBLE_CALLBACKS_ENABLED"],
                "ansible.posix.profile_tasks",
            )
            self.assertEqual(
                command["env"]["ANSIBLE_CONFIG"], str(ROOT / "ansible/ansible.cfg")
            )
        self.assertEqual(report[:2], ["Initial deployment", "Ansible apply:"])
        self.assertRegex(report[2], r"^Ansible ran 2 tasks in 0m48s; median ")
        self.assertEqual(
            report[3:6],
            [
                "Slowest Ansible tasks:",
                "   45.0s  stack_deploy : Wait for all stack services to converge",
                "    3.0s  Connect",
            ],
        )
        self.assertEqual(report[6], "Ansible verify:")
        self.assertEqual(len(report), 11)

    def test_a_log_without_timings_says_so(self):
        self.assertEqual(
            timings.summary(["TASK [Connect] ****", "ok: [manager]"]),
            ["No Ansible task timings were recorded."],
        )


if __name__ == "__main__":
    unittest.main()
