"""A failed release names its failed tasks publicly, and never their output."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from support import ROOT, ansible, load_script

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


if __name__ == "__main__":
    unittest.main()
