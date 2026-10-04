"""Load every public playbook with real roles and installed collections."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from support import ROOT, ansible


class PlaybookTests(unittest.TestCase):
    def test_administrator_setup_delegates_reports_and_propagates_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            inventory = directory / "hosts.ini"
            inventory.write_text(
                "[swarm_manager]\nlocalhost ansible_connection=local\n"
                "[all:vars]\nansible_become=false\nstack_name=off-key\n"
                "superuser_mail=admin@example.com\n"
                f"ansible_python_interpreter={sys.executable}\n"
            )
            docker = directory / "docker"
            docker.write_text(
                f"#!{sys.executable}\n"
                + """
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args[:2] == ["service", "ps"]:
    print(json.dumps({"ID": "tactic-task", "Node": "localhost", "CurrentState": "Running 1 minute ago"}))
elif args[0] == "ps":
    print("tactic-1")
elif args[0] == "exec":
    Path(os.environ["BOOTSTRAP_COMMAND_FILE"]).write_text(json.dumps(args))
    status = os.environ["BOOTSTRAP_STATUS"]
    if status == "failed":
        print("Administrator invitation saved, but email delivery failed.", file=sys.stderr)
        sys.exit(1)
    print(json.dumps({"status": status}))
else:
    sys.exit(2)
"""
            )
            docker.chmod(0o755)
            command_file = directory / "command.json"
            for status in ("sent", "pending", "configured", "failed"):
                with self.subTest(status=status):
                    env = os.environ | {
                        "PATH": str(directory) + os.pathsep + os.environ["PATH"],
                        "ANSIBLE_CONFIG": str(ROOT / "ansible/ansible.cfg"),
                        "BOOTSTRAP_COMMAND_FILE": str(command_file),
                        "BOOTSTRAP_STATUS": status,
                    }
                    resend = status == "sent"
                    result = ansible(
                        "playbook",
                        "-i",
                        str(inventory),
                        str(ROOT / "ansible/bootstrap-admin.yml"),
                        "-e",
                        json.dumps({"bootstrap_admin_resend": resend}),
                        env=env,
                        check=False,
                    )
                    expected = [
                        "exec",
                        "tactic-1",
                        "/app/bin/python",
                        "-m",
                        "off_key_tactic_middleware.bootstrap_admin",
                        "--send-email",
                    ]
                    if resend:
                        expected.append("--resend")
                    self.assertTrue(
                        command_file.exists(), result.stdout + result.stderr
                    )
                    self.assertEqual(json.loads(command_file.read_text()), expected)
                    if status == "failed":
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("email delivery failed", result.stdout)
                    else:
                        self.assertEqual(
                            result.returncode, 0, result.stdout + result.stderr
                        )
                        self.assertIn(
                            "changed=1" if status == "sent" else "changed=0",
                            result.stdout,
                        )
                        if status == "pending":
                            self.assertIn("make invite-admin-prod", result.stdout)

    def test_playbook_syntax(self):
        # Populate the actual group names without loading any operator inventory.
        with tempfile.TemporaryDirectory() as directory:
            inventory = Path(directory) / "hosts.ini"
            inventory.write_text(
                "[swarm_manager]\nlocalhost ansible_connection=local\n"
                "[ambibox_nfs]\nlocalhost\n[swarm_backend]\nbackend\n"
                "[swarm_frontend]\nfrontend\n[swarm_worker:children]\n"
                "swarm_backend\nswarm_frontend\n[all:vars]\noffkey_env=prod\n"
            )
            for playbook in sorted((ROOT / "ansible").glob("*.yml")):
                if playbook.name == "requirements.yml":
                    continue
                with self.subTest(playbook=playbook.name):
                    ansible(
                        "playbook",
                        "--syntax-check",
                        "-i",
                        str(inventory),
                        str(playbook),
                    )
