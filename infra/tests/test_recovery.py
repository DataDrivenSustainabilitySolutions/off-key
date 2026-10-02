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

from support import ROOT, ansible, run

spec = importlib.util.spec_from_file_location(
    "trust_ssh_host", ROOT / "scripts/trust_ssh_host.py"
)
trust = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trust)


class RecoveryTests(unittest.TestCase):
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
