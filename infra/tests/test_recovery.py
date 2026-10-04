"""Exercise backup and seed restoration with fake credentials and no network."""

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import yaml

from support import ROOT, ansible, run

spec = importlib.util.spec_from_file_location(
    "trust_ssh_host", ROOT / "scripts/trust_ssh_host.py"
)
trust = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trust)


class RecoveryTests(unittest.TestCase):
    def test_mqtt_credential_transfer_is_private_and_always_cleans_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transfers = root / "transfers"
            transfers.mkdir(mode=0o700)
            access = {
                "mqtt_username": "fixture-vendor",
                "mqtt_password": "fixture-transfer-password",
            }
            docker = root / "docker"
            docker.write_text(
                f"#!{sys.executable}\n"
                + """
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
if args[0] == "ps":
    counter = Path(os.environ["DOCKER_COUNTER"])
    count = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(count))
    print(f"emqx-{count}")
elif args[0] == "exec":
    connectors = json.loads(os.environ["MQTT_CONNECTORS"])
    if os.environ.get("FAIL_RECOVERY") == "1" and args[1] == "emqx-2":
        connectors["ambibox"]["password"] = "******"
    print(json.dumps(connectors))
else:
    sys.exit(2)
"""
            )
            docker.chmod(0o755)
            counter = root / "counter"
            env = os.environ | {
                "PATH": str(root) + os.pathsep + os.environ["PATH"],
                "TMPDIR": str(transfers),
                "ANSIBLE_CONFIG": str(ROOT / "ansible/ansible.cfg"),
                "DOCKER_COUNTER": str(counter),
                "MQTT_CONNECTORS": json.dumps(
                    {
                        "ambibox": {
                            "username": access["mqtt_username"],
                            "password": access["mqtt_password"],
                        }
                    }
                ),
            }
            result = run(
                sys.executable,
                str(ROOT / "scripts/read-ambibox-mqtt-access.py"),
                "off-key",
                env=env,
            )
            self.assertNotIn(access["mqtt_password"], result.stdout + result.stderr)
            transfer = Path(result.stdout.strip())
            self.assertEqual(json.loads(transfer.read_text()), access)
            self.assertEqual(stat.S_IMODE(transfer.stat().st_mode), 0o600)
            transfer.unlink()

            # Exercise the actual transfer and resolution tasks without the later
            # root-owned production persistence step.
            tasks = yaml.safe_load(
                (
                    ROOT / "ansible/roles/stack_prepare/tasks/ambibox-access.yml"
                ).read_text()
            )
            recovery = next(task for task in tasks if "block" in task)
            resolution = next(
                task
                for task in tasks
                if "ambibox_initial_access" in task.get("set_fact", {})
            )
            recovered = root / "recovered.json"
            playbook = root / "recover.yml"
            playbook.write_text(
                yaml.safe_dump(
                    [
                        {
                            "hosts": "swarm_manager",
                            "gather_facts": False,
                            "vars": {
                                "role_path": str(ROOT / "ansible/roles/stack_prepare"),
                                "stack_name": "off-key",
                                "ambibox_access_file": {"stat": {"exists": False}},
                            },
                            "tasks": [
                                recovery,
                                resolution,
                                {
                                    "copy": {
                                        "dest": str(recovered),
                                        "content": "{{ ambibox_initial_access | to_json }}",
                                        "mode": "0600",
                                    },
                                    "no_log": True,
                                },
                            ],
                        }
                    ]
                )
            )
            inventory = root / "hosts.ini"
            inventory.write_text(
                "[swarm_manager]\nmanager ansible_connection=local\n"
                "[swarm_backend]\nfirst ansible_connection=local\n"
                "second ansible_connection=local\n[all:vars]\n"
                "ansible_become=false\n"
                f"ansible_python_interpreter={sys.executable}\n"
            )
            for fail in (False, True):
                with self.subTest(fail=fail):
                    counter.unlink()
                    result = ansible(
                        "playbook",
                        "-i",
                        str(inventory),
                        str(playbook),
                        env=env | {"FAIL_RECOVERY": "1" if fail else "0"},
                        check=False,
                    )
                    self.assertNotIn(
                        access["mqtt_password"], result.stdout + result.stderr
                    )
                    self.assertEqual(list(transfers.glob("offkey-ambibox-*")), [])
                    if fail:
                        self.assertNotEqual(result.returncode, 0)
                    else:
                        self.assertEqual(
                            result.returncode, 0, result.stdout + result.stderr
                        )
                        self.assertEqual(json.loads(recovered.read_text()), access)

    def test_complete_backup_can_seed_an_empty_host_without_overwriting_live_identity(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live, backup, restored = (
                root / name for name in ("live", "backup", "restored")
            )
            for stack in (live, restored):
                (stack / "tailscale-ambibox-data").mkdir(parents=True)
            identity = '{"test-only-identity":"synthetic-not-a-real-key"}\n'
            access = json.dumps(
                {
                    "mqtt_username": "fixture",
                    "mqtt_password": "fixture-password",
                    "api_key": "fixture",
                    "api_secret": "a" * 64,
                    "gost_password": "b" * 64,
                }
            )
            (live / "tailscale-ambibox-data/tailscaled.state").write_text(identity)
            (live / "ambibox-access.json").write_text(access)
            inventory = root / "hosts.ini"
            inventory.write_text(
                "[ambibox_nfs]\nlocalhost ansible_connection=local\n[swarm_manager]\nlocalhost\n"
            )
            variables = {
                "stack_dir": str(live),
                "ambibox_backup_directory": str(backup),
                "offkey_env": "dev",
                "ansible_become": False,
                "ansible_python_interpreter": sys.executable,
            }
            ansible(
                "playbook",
                "-i",
                str(inventory),
                str(ROOT / "ansible/backup-ambibox-state.yml"),
                "-e",
                json.dumps(variables),
            )
            for line in (backup / "SHA256SUMS").read_text().splitlines():
                digest, filename = line.split("  ")
                saved = backup / filename
                self.assertEqual(hashlib.sha256(saved.read_bytes()).hexdigest(), digest)
                self.assertEqual(stat.S_IMODE(saved.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(backup.stat().st_mode), 0o700)
            variables |= {
                "stack_dir": str(restored),
                "ambibox_seed_dir": str(backup / "tailscale-ambibox-data"),
                "stack_file_owner": str(os.getuid()),
                "stack_file_group": str(os.getgid()),
            }
            command = (
                "playbook",
                "-i",
                "localhost,",
                str(ROOT / "tests/recover-ambibox.yml"),
                "-e",
                json.dumps(variables),
            )
            ansible(*command)
            self.assertEqual(
                (restored / "tailscale-ambibox-data/tailscaled.state").read_text(),
                identity,
            )
            self.assertEqual((restored / "ambibox-access.json").read_text(), access)
            (restored / "tailscale-ambibox-data/tailscaled.state").write_text(
                "newer-live-identity"
            )
            (restored / "ambibox-access.json").write_text("newer-live-access")
            ansible(*command)
            self.assertEqual(
                (restored / "tailscale-ambibox-data/tailscaled.state").read_text(),
                "newer-live-identity",
            )
            self.assertEqual(
                (restored / "ambibox-access.json").read_text(), "newer-live-access"
            )

    def test_ssh_enrollment_requires_the_trusted_fingerprint_and_preserves_existing_hosts(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = root / "host"
            run("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key))
            fingerprint = run(
                "ssh-keygen", "-lf", str(key) + ".pub", "-E", "sha256"
            ).stdout.split()[1]
            public = Path(str(key) + ".pub").read_text().split()
            scanned = f"[127.0.0.1]:2222 {public[0]} {public[1]}\n"
            known_hosts = root / "known_hosts"
            unrelated = f"unrelated.example {public[0]} {public[1]}\n"
            known_hosts.write_text(unrelated)
            original_mode = stat.S_IMODE(known_hosts.stat().st_mode)
            actual_run = subprocess.run

            def command(args, **kwargs):
                if args[0] == "ssh-keyscan":
                    return subprocess.CompletedProcess(args, 0, scanned, "")
                return actual_run(args, **kwargs)

            with patch.object(trust.subprocess, "run", side_effect=command):
                with self.assertRaisesRegex(ValueError, "mismatch"):
                    trust.enroll("127.0.0.1", 2222, "SHA256:" + "A" * 43, known_hosts)
                self.assertEqual(known_hosts.read_text(), unrelated)
                trust.enroll("127.0.0.1", 2222, fingerprint, known_hosts)
                saved = known_hosts.read_text()
                trust.enroll("127.0.0.1", 2222, fingerprint, known_hosts)
                self.assertEqual(known_hosts.read_text(), saved)
                fresh_hosts = root / "new_known_hosts"
                trust.enroll("127.0.0.1", 2222, fingerprint, fresh_hosts)
                self.assertEqual(stat.S_IMODE(fresh_hosts.stat().st_mode), 0o600)

            def concurrent_command(args, **kwargs):
                if args[0] == "ssh-keyscan":
                    record = f"{args[-1]} {public[0]} {public[1]}\n"
                    return subprocess.CompletedProcess(args, 0, record, "")
                return actual_run(args, **kwargs)

            with (
                patch.object(trust.subprocess, "run", side_effect=concurrent_command),
                ThreadPoolExecutor(max_workers=2) as pool,
            ):
                jobs = [
                    pool.submit(trust.enroll, host, 22, fingerprint, known_hosts)
                    for host in ("first.example", "second.example")
                ]
                for job in jobs:
                    job.result()
            saved = known_hosts.read_text()
            self.assertIn("first.example ", saved)
            self.assertIn("second.example ", saved)
            self.assertIn(unrelated, saved)
            self.assertIn(scanned, saved)
            self.assertEqual(stat.S_IMODE(known_hosts.stat().st_mode), original_mode)
