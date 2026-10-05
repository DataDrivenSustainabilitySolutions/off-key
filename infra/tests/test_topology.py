"""Reject unsupported inventories before any production host operation."""

import sys
import tempfile
import unittest
from pathlib import Path

from support import ROOT, ansible


class TopologyTests(unittest.TestCase):
    def test_every_operator_playbook_rejects_missing_or_multiple_managers(self):
        playbooks = [
            path
            for path in sorted((ROOT / "ansible").glob("*.yml"))
            if path.name not in {"requirements.yml", "validate-inventory.yml"}
        ]
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory) / "hosts.ini"
            for managers in ([], ["manager1", "manager2"]):
                inventory.write_text(
                    "[swarm_manager]\n"
                    + "\n".join(managers)
                    + "\n[ambibox_nfs]\nbackend\n[swarm_backend]\nbackend\n"
                    "[swarm_frontend]\nfrontend\n[swarm_worker:children]\n"
                    "swarm_backend\nswarm_frontend\n[all:vars]\n"
                    "ansible_connection=local\nansible_become=false\n"
                    f"ansible_python_interpreter={sys.executable}\n"
                )
                for playbook in playbooks:
                    with self.subTest(managers=managers, playbook=playbook.name):
                        result = ansible(
                            "playbook",
                            "-i",
                            str(inventory),
                            str(playbook),
                            check=False,
                        )
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(
                            "must contain exactly one swarm_manager host",
                            result.stdout,
                        )
                        self.assertEqual(result.stdout.count("PLAY ["), 1)

    def test_single_manager_passes_controller_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory) / "hosts.ini"
            inventory.write_text("[swarm_manager]\nmanager1\n")
            ansible(
                "playbook",
                "-i",
                str(inventory),
                str(ROOT / "ansible/validate-inventory.yml"),
            )
