"""Recovery must fence actual worker tasks, independently of desired replicas."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from persistence_fixture import DOCKER
from support import ROOT, ansible, run


class RecoveryWriterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        timestamp = "20260807T120000Z"
        backup = self.root / "backups/postgres" / timestamp
        backup.mkdir(parents=True)
        (backup / "roles.sql").write_text("-- synthetic roles")
        (backup / "fixture_db.dump").write_text("synthetic saved data")
        run(
            sys.executable,
            str(ROOT / "scripts/backup_manifest.py"),
            "create",
            str(backup),
            "postgres",
            timestamp,
            "roles.sql",
            "fixture_db.dump",
        )
        (self.root / "stack").mkdir()
        self.pending = self.root / "stack/recovery-pending.json"
        self.plan = {
            "version": 1,
            "phase": "restore",
            "timestamp": timestamp,
            "services": ["postgres"],
            "backup_paths": {"postgres": str(backup)},
            "backup_files": {"postgres": ["fixture_db.dump", "roles.sql"]},
            "writer_replicas": {"off-key_api": 1, "radar-runtime": 2},
            "flips": [],
            "service_nodes": {},
            "service_tasks": {},
        }
        self.original_plan = json.dumps(self.plan)
        self.pending.write_text(self.original_plan)
        self.replicas = {
            "off-key_postgres": 1,
            "off-key_api": 1,
            "radar-runtime": 2,
            "radar-new": 0,
        }
        (self.root / "docker").write_text(f"#!{sys.executable}\n" + DOCKER)
        (self.root / "docker").chmod(0o755)

        # Exercise the canonical wait task with only its retry budget shortened.
        roles = self.root / "ansible/roles"
        role = roles / "persistence_switch"
        shutil.copytree(ROOT / "ansible/roles/persistence_switch", role)
        wait_path = role / "tasks/wait_stopped.yml"
        wait = yaml.safe_load(wait_path.read_text())
        wait[0].update(retries=1, delay=0)
        wait_path.write_text(yaml.safe_dump(wait))
        (roles / "swarm_task").symlink_to(ROOT / "ansible/roles/swarm_task")
        # Quiescing reuses the deployment role to find this stack's workers.
        (roles / "stack_deploy").symlink_to(ROOT / "ansible/roles/stack_deploy")
        (self.root / "scripts").symlink_to(ROOT / "scripts")
        self.playbook = self.root / "restore.yml"
        self.playbook.write_text(
            yaml.safe_dump(
                [
                    {
                        "hosts": "localhost",
                        "gather_facts": False,
                        "tasks": [
                            {
                                "include_role": {
                                    "name": "persistence_switch",
                                    "tasks_from": "manual_restore",
                                }
                            }
                        ],
                    }
                ]
            )
        )
        self.variables = {
            "ansible_connection": "local",
            "ansible_become": False,
            "ansible_python_interpreter": sys.executable,
            "ansible_remote_tmp": str(self.root / "remote-tmp"),
            "persistence_switch_confirm": True,
            "stack_name": "off-key",
            "postgres_user": "fixture",
            "stack_dir": str(self.root / "stack"),
            "persistence_backup_dir": str(self.root / "backups"),
            "restore_from": timestamp,
            "restore_services": "postgres",
        }
        self.env = os.environ | {
            "PATH": str(self.root) + os.pathsep + os.environ["PATH"],
            "DOCKER_FIXTURE": str(self.root),
            "MANUAL_RESTORE": "1",
            "ANSIBLE_CONFIG": str(ROOT / "ansible/ansible.cfg"),
            "ANSIBLE_ROLES_PATH": str(roles),
            "ANSIBLE_LOCAL_TEMP": str(self.root / "ansible-tmp"),
            "ANSIBLE_REMOTE_TEMP": str(self.root / "remote-tmp"),
        }

    def recover(self, task_states):
        (self.root / "state.json").write_text(
            json.dumps(
                {
                    "replicas": self.replicas,
                    "deployed": False,
                    "task_state_sequences": {"radar-new": task_states},
                }
            )
        )
        result = ansible(
            "playbook",
            "-i",
            "localhost,",
            str(self.playbook),
            "-e",
            json.dumps(self.variables),
            env=self.env,
            check=False,
        )
        state = json.loads((self.root / "state.json").read_text())
        commands = [
            json.loads(line)
            for line in (self.root / "commands.jsonl").read_text().splitlines()
        ]
        return result, state, commands

    def test_zero_replicas_with_live_task_blocks_recovery_before_writer_changes(self):
        result, state, commands = self.recover(["running"])
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Wait for every task to stop", result.stdout)
        self.assertEqual(state["replicas"], self.replicas)
        self.assertEqual(self.pending.read_text(), self.original_plan)
        self.assertFalse(
            any(
                command[:2] == ["service", "scale"] or "pg_restore" in command
                for command in commands
            )
        )
        self.assertTrue(any("radar-new-task" in command for command in commands))

    def test_recovery_waits_for_retiring_task_and_keeps_extra_worker_stopped(self):
        result, state, commands = self.recover(["running", "shutdown"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(state["replicas"], self.replicas)
        self.assertFalse(self.pending.exists())
        self.assertTrue(any("pg_restore" in command for command in commands))
        first_scale = next(
            index
            for index, command in enumerate(commands)
            if command[:2] == ["service", "scale"]
        )
        task_checks = [
            command
            for command in commands[:first_scale]
            if command[:3] == ["inspect", "--type", "task"]
            and "radar-new-task" in command
        ]
        self.assertEqual(len(task_checks), 2)
        self.assertFalse(
            any(
                command[:2] == ["service", "scale"]
                and command[2].startswith("radar-new=")
                for command in commands
            )
        )
