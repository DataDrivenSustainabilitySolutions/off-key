"""Load every public playbook with real roles and installed collections."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
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
                + r"""
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args[:2] == ["service", "ps"]:
    print(json.dumps({"ID": "tactic-task", "Node": "localhost", "CurrentState": "Running 1 minute ago"}))
elif args[0] == "ps":
    if "label=com.docker.swarm.task.id=tactic-task" in args:
        assert args == ["ps", "--quiet", "--no-trunc", "--filter",
                        "label=com.docker.swarm.task.id=tactic-task", "--filter", "status=running"]
        print("tactic-1")
    else:
        print("retiring-tactic\ntactic-1")
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

    def test_readiness_refreshes_the_exact_task_and_retries_until_ready(self):
        for replace_task in (False, True):
            with (
                self.subTest(replace_task=replace_task),
                tempfile.TemporaryDirectory() as directory,
            ):
                directory = Path(directory)
                playbook_directory = directory / "ansible"
                playbook_directory.mkdir()
                task_directory = ROOT / "ansible/roles/stack_deploy/tasks"
                (playbook_directory / "application_readiness.yml").write_text(
                    (task_directory / "application_readiness.yml").read_text()
                )
                attempt = yaml.safe_load(
                    (task_directory / "application_readiness_attempt.yml").read_text()
                )
                # Run the actual attempt flow with only its fixture delay shortened.
                for task in attempt[0]["block"]:
                    if "pause" in task:
                        task["pause"]["seconds"] = 0
                (playbook_directory / "application_readiness_attempt.yml").write_text(
                    yaml.safe_dump(attempt)
                )
                scripts = directory / "scripts"
                scripts.mkdir()
                (scripts / "check_application.py").write_text(
                    (ROOT / "scripts/check_application.py").read_text()
                )
                inventory = directory / "hosts.ini"
                inventory.write_text(
                    "[swarm_manager]\nlocalhost ansible_connection=local\n"
                    "[all:vars]\nansible_become=false\nstack_name=off-key\n"
                    f"ansible_python_interpreter={sys.executable}\n"
                )
                docker = directory / "docker"
                docker.write_text(
                    f"#!{sys.executable}\n"
                    + r"""
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
root = Path(os.environ["PROBE_FIXTURE"])
attempts_file = root / "attempts"
attempts = int(attempts_file.read_text()) if attempts_file.exists() else 0
replaced = os.environ["REPLACE_TASK"] == "1" and attempts > 0
task_id = "worker-replacement-task" if replaced else "worker-task"
container = "worker-replacement" if replaced else "worker-active"
with (root / "commands.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\n")
if args[:2] == ["service", "ps"]:
    assert args[2] == "off-key_mqtt-proxy"
    print(json.dumps({"ID": task_id, "Node": "localhost", "CurrentState": "Running 1 minute ago"}))
elif args[0] == "ps":
    if f"label=com.docker.swarm.task.id={task_id}" in args:
        print(container)
    else:
        print("retiring-worker\n" + container)
elif args[0] == "exec":
    assert args == ["exec", "-i", container, "/app/bin/python", "-"]
    assert sys.stdin.read()
    attempts += 1
    attempts_file.write_text(str(attempts))
    if attempts == 1:
        sys.exit("worker is still initializing")
    print("worker ready")
else:
    sys.exit("Unexpected Docker command: " + repr(args))
"""
                )
                docker.chmod(0o755)
                playbook = playbook_directory / "probe.yml"
                playbook.write_text(
                    yaml.safe_dump(
                        [
                            {
                                "hosts": "swarm_manager",
                                "gather_facts": False,
                                "tasks": [
                                    {"include_tasks": "application_readiness.yml"}
                                ],
                            }
                        ]
                    )
                )
                result = ansible(
                    "playbook",
                    "-i",
                    str(inventory),
                    str(playbook),
                    env=os.environ
                    | {
                        "PATH": str(directory) + os.pathsep + os.environ["PATH"],
                        "ANSIBLE_CONFIG": str(ROOT / "ansible/ansible.cfg"),
                        "PROBE_FIXTURE": str(directory),
                        "REPLACE_TASK": "1" if replace_task else "0",
                    },
                )
                self.assertEqual((directory / "attempts").read_text(), "2")
                commands = [
                    json.loads(line)
                    for line in (directory / "commands.jsonl").read_text().splitlines()
                ]
                lookups = [command for command in commands if command[0] == "ps"]
                self.assertEqual(len(lookups), 2)
                task_ids = [
                    "worker-task",
                    "worker-replacement-task" if replace_task else "worker-task",
                ]
                for lookup, task_id in zip(lookups, task_ids):
                    self.assertIn(f"label=com.docker.swarm.task.id={task_id}", lookup)
                self.assertIn("changed=0", result.stdout)

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
