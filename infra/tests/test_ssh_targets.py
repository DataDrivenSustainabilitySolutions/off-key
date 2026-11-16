"""A failed release can name each SSH target and whether the runner trusts it."""

import tempfile
import unittest
from pathlib import Path

from support import load_script

ssh = load_script("ssh_targets")
KEY = "AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
OTHER = "AAAAC3NzaC1lZDI1NTE5AAAAIHo0y0f4j8m0b2lGgvKm1bXx0sQwV7XcJ0r6m2y9Yt1Q"
INVENTORY = {
    "_meta": {
        "hostvars": {
            "manager": {"ansible_host": "100.64.0.1", "ansible_user": "deploy"},
            "worker": {
                "ansible_host": "100.64.0.2",
                "ansible_port": 2222,
                "ansible_user": "deploy",
            },
        }
    },
    "all": {"children": ["swarm_manager", "swarm_worker", "ungrouped"]},
    "swarm_manager": {"hosts": ["manager"]},
    "swarm_backend": {"hosts": ["worker"]},
    "swarm_frontend": {"hosts": ["worker"]},
}


class SshTargetTests(unittest.TestCase):
    def test_targets_follow_ansible_defaults(self):
        targets = ssh.targets(INVENTORY)
        self.assertEqual(
            targets["manager"],
            {
                "address": "100.64.0.1",
                "port": 22,
                "user": "deploy",
                "groups": ["swarm_manager"],
            },
        )
        self.assertEqual(targets["worker"]["port"], 2222)
        self.assertEqual(
            targets["worker"]["groups"], ["swarm_backend", "swarm_frontend"]
        )
        bare = ssh.targets({"_meta": {"hostvars": {"node": {}}}})
        self.assertEqual(bare["node"]["address"], "node")
        self.assertEqual(bare["node"]["user"], "ansible")

    def test_known_hosts_entries_are_matched_by_address_and_port(self):
        with tempfile.TemporaryDirectory() as directory:
            known = Path(directory) / "known_hosts"
            known.write_text(
                f"100.64.0.1 ssh-ed25519 {KEY}\n[100.64.0.2]:2222 ssh-ed25519 {OTHER}\n"
            )
            self.assertEqual(
                ssh.known_keys(known, "100.64.0.1", 22), {("ssh-ed25519", KEY)}
            )
            self.assertEqual(ssh.known_keys(known, "100.64.0.1", 2222), set())
            self.assertEqual(ssh.known_keys(known, "100.64.0.2", 22), set())
            self.assertEqual(
                ssh.known_keys(known, "100.64.0.2", 2222), {("ssh-ed25519", OTHER)}
            )

    def test_description_compares_with_the_other_stack(self):
        demo = ssh.targets(INVENTORY)
        prod = ssh.targets(INVENTORY)
        prod["manager"] = dict(prod["manager"], address="netcup-vps")
        trusted = {("ssh-ed25519", KEY)}
        self.assertEqual(
            ssh.describe(
                "manager", demo["manager"], set(), trusted, prod, "production"
            ),
            "SSH target manager (swarm_manager): deploy@100.64.0.1 port 22; "
            "known-hosts entry: no; same as production: no",
        )
        self.assertEqual(
            ssh.describe(
                "worker", demo["worker"], trusted, trusted, prod, "production"
            ),
            "SSH target worker (swarm_backend, swarm_frontend): deploy@100.64.0.2 "
            "port 2222; known-hosts entry: yes; host key: matches; "
            "same as production: yes",
        )
        self.assertIn(
            "host key: differs",
            ssh.describe(
                "worker", demo["worker"], trusted, {("ssh-ed25519", OTHER)}, None, "x"
            ),
        )
        self.assertIn(
            "host key: no answer",
            ssh.describe("worker", demo["worker"], trusted, None, {}, "production"),
        )
        self.assertIn(
            "not in the production inventory",
            ssh.describe("worker", demo["worker"], trusted, None, {}, "production"),
        )


if __name__ == "__main__":
    unittest.main()
