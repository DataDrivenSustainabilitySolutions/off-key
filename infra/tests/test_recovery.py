"""Exercise backup and seed restoration with fake credentials and no network."""

import hashlib
import json
import stat
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import yaml
from support import ROOT, ansible, load_script, run

trust = load_script("trust_ssh_host")


class RecoveryTests(unittest.TestCase):
    def test_route_login_comes_only_from_the_vault(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "legacy-access.json"
            legacy.write_text(
                json.dumps(
                    {"mqtt_username": "legacy-user", "mqtt_password": "legacy-pass"}
                )
            )
            resolved = root / "resolved.json"
            playbook = root / "resolve.yml"
            playbook.write_text(
                yaml.safe_dump(
                    [
                        {
                            "hosts": "localhost",
                            "connection": "local",
                            "gather_facts": False,
                            "tasks": [
                                {
                                    "include_role": {
                                        "name": "stack_prepare",
                                        "tasks_from": "broker-route-access",
                                    }
                                },
                                {
                                    "copy": {
                                        "dest": str(resolved),
                                        "content": "{{ broker_route_login | to_json }}",
                                        "mode": "0600",
                                    },
                                    "no_log": True,
                                },
                            ],
                        }
                    ]
                )
            )
            base = {
                "ansible_become": False,
                "ansible_python_interpreter": sys.executable,
                "stack_dir": str(root),
                "broker_route_host_suffixes": [".mesh.example"],
            }
            cases = [
                (
                    {
                        "broker_route_mqtt_username": "vault-user",
                        "broker_route_mqtt_password": "vault-pass",
                    },
                    {"username": "vault-user", "password": "vault-pass"},
                ),
                ({}, None),
                # A login file an earlier release left behind is never read.
                ({"broker_route_legacy_access_file": str(legacy)}, None),
                ({"broker_route_anonymous": True}, {"username": "", "password": ""}),
                (
                    {
                        "broker_route_mqtt_username": "vault-user",
                        "broker_route_mqtt_password": "vault-pass",
                        "broker_route_host_suffixes": ["mesh.example"],
                    },
                    None,
                ),
            ]
            for overrides, expected in cases:
                with self.subTest(overrides=overrides):
                    resolved.unlink(missing_ok=True)
                    result = ansible(
                        "playbook",
                        "-i",
                        "localhost,",
                        str(playbook),
                        "-e",
                        json.dumps(base | overrides),
                        check=False,
                    )
                    output = result.stdout + result.stderr
                    for secret in ("vault-pass", "legacy-pass"):
                        self.assertNotIn(secret, output)
                    if expected is None:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertFalse(resolved.exists())
                    else:
                        self.assertEqual(result.returncode, 0, output)
                        self.assertEqual(json.loads(resolved.read_text()), expected)

    def test_identity_backup_can_seed_an_empty_host_without_overwriting_live_identity(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live, backup, restored = (
                root / name for name in ("live", "backup", "restored")
            )
            for stack in (live, restored):
                (stack / "route-data").mkdir(parents=True)
            identity = '{"test-only-identity":"synthetic-not-a-real-key"}\n'
            (live / "route-data/tailscaled.state").write_text(identity)
            inventory = root / "hosts.ini"
            inventory.write_text(
                "[swarm_manager]\nlocalhost ansible_connection=local\n"
            )
            variables = {
                "stack_dir": str(live),
                "broker_route_state_dir": str(live / "route-data"),
                "broker_route_backup_directory": str(backup),
                "offkey_env": "prod",
                "ansible_become": False,
                "ansible_python_interpreter": sys.executable,
            }
            ansible(
                "playbook",
                "-i",
                str(inventory),
                str(ROOT / "ansible/backup-broker-route-state.yml"),
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
                "broker_route_state_dir": str(restored / "route-data"),
                "broker_route_seed_dir": str(backup),
            }
            command = (
                "playbook",
                "-i",
                "localhost,",
                str(ROOT / "tests/recover-broker-route.yml"),
                "-e",
                json.dumps(variables),
            )
            ansible(*command)
            self.assertEqual(
                (restored / "route-data/tailscaled.state").read_text(), identity
            )
            (restored / "route-data/tailscaled.state").write_text("newer-live-identity")
            ansible(*command)
            self.assertEqual(
                (restored / "route-data/tailscaled.state").read_text(),
                "newer-live-identity",
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
