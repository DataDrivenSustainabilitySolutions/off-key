"""A release reports where its time went publicly, and never task output."""

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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

    def test_a_log_without_timings_says_so(self):
        self.assertEqual(
            timings.summary(["TASK [Connect] ****", "ok: [manager]"]),
            ["No Ansible task timings were recorded."],
        )


if __name__ == "__main__":
    unittest.main()
