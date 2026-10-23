"""Load every public playbook with real roles and installed collections."""

import json
import os
import shutil
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
        for replacement in ("none", "after_probe", "before_container"):
            with (
                self.subTest(replacement=replacement),
                tempfile.TemporaryDirectory() as directory,
            ):
                directory = Path(directory)
                playbook_directory = directory / "ansible"
                playbook_directory.mkdir()
                task_directory = ROOT / "ansible/roles/stack_deploy/tasks"
                (playbook_directory / "application_readiness.yml").write_text(
                    (task_directory / "application_readiness.yml").read_text()
                )
                shutil.copy(
                    task_directory / "application_readiness_probe.yml",
                    playbook_directory,
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
                    "[swarm_manager]\nlocalhost\n"
                    "[swarm_worker]\nworker-one\nworker-two\n"
                    "[all:vars]\nansible_connection=local\n"
                    "ansible_become=false\nstack_name=off-key\n"
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
replacement = os.environ["REPLACEMENT"]
replaced = (root / "replaced").exists()
task_id = "worker-replacement-task" if replaced else "worker-task"
container = "worker-replacement" if replaced else "worker-active"
node = "worker-two" if replaced else "worker-one"
with (root / "commands.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\n")
if args[:2] == ["service", "ps"]:
    assert args[2] == "off-key_mqtt-proxy"
    print(json.dumps({"ID": task_id, "Node": node, "CurrentState": "Running 1 minute ago"}))
    if replacement == "before_container":
        (root / "replaced").touch()
elif args[0] == "ps":
    if f"label=com.docker.swarm.task.id={task_id}" in args:
        print(container)
    elif not any("com.docker.swarm.task.id=" in arg for arg in args):
        print("retiring-worker\n" + container)
elif args[0] == "exec":
    assert args == ["exec", "-i", container, "/app/bin/python", "-"]
    assert sys.stdin.read()
    attempts += 1
    attempts_file.write_text(str(attempts))
    if attempts == 1:
        if replacement == "after_probe":
            (root / "replaced").touch()
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
                        "REPLACEMENT": replacement,
                    },
                )
                self.assertEqual((directory / "attempts").read_text(), "2")
                commands = [
                    json.loads(line)
                    for line in (directory / "commands.jsonl").read_text().splitlines()
                ]
                lookups = [command for command in commands if command[0] == "ps"]
                original = ("worker-task", "worker-one")
                replaced = ("worker-replacement-task", "worker-two")
                expected = {
                    "none": [original, original],
                    "after_probe": [original, replaced],
                    "before_container": [original, replaced, replaced],
                }[replacement]
                self.assertEqual(len(lookups), len(expected))
                for lookup, (task_id, _) in zip(lookups, expected):
                    self.assertIn(f"label=com.docker.swarm.task.id={task_id}", lookup)
                discoveries = [
                    command for command in commands if command[:2] == ["service", "ps"]
                ]
                self.assertEqual(len(discoveries), len(expected))
                original_queries = sum(node == "worker-one" for _, node in expected)
                original_probes = {"none": 2, "after_probe": 1, "before_container": 0}[
                    replacement
                ]
                self.assertEqual(
                    result.stdout.count("ok: [localhost -> worker-one]"),
                    original_queries + original_probes,
                )
                self.assertEqual(
                    result.stdout.count("ok: [localhost -> worker-two]"),
                    len(expected) - original_queries + 2 - original_probes,
                )
                self.assertIn("changed=0", result.stdout)

    def test_task_resolution_clears_stale_outputs_and_strict_callers_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            role = directory / "roles/swarm_task"
            shutil.copytree(ROOT / "ansible/roles/swarm_task", role)
            main = yaml.safe_load((role / "tasks/main.yml").read_text())
            main[1]["loop"] = "{{ range(1) | list }}"
            (role / "tasks/main.yml").write_text(yaml.safe_dump(main))
            retry = yaml.safe_load((role / "tasks/retry.yml").read_text())
            retry[0]["block"][0]["pause"]["seconds"] = 0
            (role / "tasks/retry.yml").write_text(yaml.safe_dump(retry))
            docker = directory / "docker"
            docker.write_text(
                f"#!{sys.executable}\n"
                + r"""
import json, sys
args = sys.argv[1:]
if args[:2] == ["service", "ps"]:
    service = args[2].removeprefix("off-key_")
    if service != "missing-task":
        print(json.dumps({"ID": service + "-task", "Node": "localhost", "CurrentState": "Running 1 minute ago"}))
elif args[0] == "ps":
    if "label=com.docker.swarm.task.id=tactic-task" in args:
        print("tactic-container")
else:
    sys.exit("Unexpected Docker command: " + repr(args))
"""
            )
            docker.chmod(0o755)
            tasks = []
            for missing in ("missing-task", "missing-container"):
                tasks.extend(
                    [
                        {
                            "include_role": {
                                "name": "swarm_task",
                                "tasks_from": "resolve",
                            },
                            "vars": {"svc": "tactic"},
                        },
                        {
                            "assert": {
                                "that": [
                                    "svc_node == 'localhost'",
                                    "svc_task_id == 'tactic-task'",
                                    "svc_container == 'tactic-container'",
                                ]
                            }
                        },
                        {
                            "include_role": {
                                "name": "swarm_task",
                                "tasks_from": "resolve",
                            },
                            "vars": {"svc": missing},
                        },
                        {
                            "assert": {
                                "that": [
                                    "svc_node == ''",
                                    "svc_task_id == ''",
                                    "svc_container == ''",
                                    "svc_resolution_error | length > 0",
                                ]
                            }
                        },
                    ]
                )
            tasks.append(
                {
                    "include_role": {"name": "swarm_task"},
                    "vars": {"svc": "missing-container"},
                }
            )
            playbook = directory / "probe.yml"
            playbook.write_text(
                yaml.safe_dump(
                    [
                        {
                            "hosts": "localhost",
                            "connection": "local",
                            "gather_facts": False,
                            "become": False,
                            "vars": {
                                "stack_name": "off-key",
                                "ansible_python_interpreter": sys.executable,
                            },
                            "tasks": tasks,
                        }
                    ]
                )
            )
            result = ansible(
                "playbook",
                "-i",
                "localhost,",
                str(playbook),
                env=os.environ
                | {
                    "PATH": str(directory) + os.pathsep + os.environ["PATH"],
                    "ANSIBLE_CONFIG": str(ROOT / "ansible/ansible.cfg"),
                    "ANSIBLE_ROLES_PATH": str(directory / "roles"),
                },
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "missing-container | require a running task and its container",
                result.stdout,
            )
            self.assertIn(
                "Expected exactly one running container for task missing-container-task on localhost.",
                result.stdout,
            )
            self.assertNotIn("Assertion failed", result.stdout)

    def test_release_maintenance_stops_only_database_writers(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            docker = directory / "docker"
            docker.write_text(
                f"#!{sys.executable}\n"
                + r"""
import sys
args = sys.argv[1:]
assert args[:4] == ["service", "ls", "--format", "{{.Name}}"], args
listings = {
    "label=com.docker.stack.namespace=off-key": [
        "off-key_postgres", "off-key_emqx-main", "off-key_cloudflared",
        "off-key_traefik", "off-key_landing", "off-key_frontend", "off-key_api",
        "off-key_tactic", "off-key_db-sync", "off-key_mqtt-proxy", "off-key_retired",
    ],
    "label=managed_by=tactic": ["radar-worker"],
}
print("\n".join(listings[args[5]]))
"""
            )
            docker.chmod(0o755)
            database = {"POSTGRES_HOST": "postgres", "POSTGRES_DB": "postgres"}
            services = {
                "postgres": {"environment": {"POSTGRES_DB": "postgres"}},
                "emqx-main": {"environment": {}},
                "cloudflared": {},
                "traefik": {},
                "landing": {},
                "frontend": {},
                "api": {"environment": {"LOG_LEVEL": "INFO"}},
                "tactic": {"environment": database},
                "db-sync": {"environment": database},
                "mqtt-proxy": {"environment": database},
            }
            output = directory / "writers.json"
            playbook = directory / "writers.yml"
            playbook.write_text(
                yaml.safe_dump(
                    [
                        {
                            "hosts": "localhost",
                            "connection": "local",
                            "become": False,
                            "gather_facts": False,
                            "vars": {
                                "stack_name": "off-key",
                                "stack_compose_model": {"services": services},
                            },
                            "tasks": [
                                {
                                    "include_tasks": str(
                                        ROOT
                                        / "ansible/roles/stack_deploy/tasks/release_writers.yml"
                                    )
                                },
                                {
                                    "copy": {
                                        "content": "{{ release_writers | to_json }}",
                                        "dest": str(output),
                                    }
                                },
                            ],
                        }
                    ]
                )
            )
            env = os.environ | {
                "PATH": str(directory) + os.pathsep + os.environ["PATH"],
                "ANSIBLE_CONFIG": str(ROOT / "ansible/ansible.cfg"),
            }
            ansible(
                "playbook",
                "-i",
                "localhost,",
                "-e",
                f"ansible_python_interpreter={sys.executable}",
                str(playbook),
                env=env,
            )
            self.assertEqual(
                sorted(json.loads(output.read_text())),
                [
                    "off-key_db-sync",
                    "off-key_mqtt-proxy",
                    "off-key_retired",
                    "off-key_tactic",
                    "radar-worker",
                ],
            )

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
