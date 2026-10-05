"""Release triggers and private runner material use fail-closed trust boundaries."""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml
from support import ROOT, ansible, run


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release = load("pin_release")
with patch.dict(sys.modules, {"pin_release": release}):
    readiness = load("release_ready")
secrets = load("prepare_ci_secrets")


class CDTests(unittest.TestCase):
    def test_only_main_pushes_from_this_repository_can_trigger_production(self):
        run = {
            "event": "push",
            "head_branch": "main",
            "head_sha": "a" * 40,
            "head_repository": {"full_name": release.REPOSITORY},
            "conclusion": "success",
        }
        self.assertEqual(
            readiness.candidate({"workflow_run": run}, "workflow_run"), "a" * 40
        )
        for changes in [
            {"event": "pull_request"},
            {"head_branch": "feature"},
            {"head_repository": {"full_name": "attacker/fork"}},
            {"conclusion": "failure"},
        ]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                readiness.candidate({"workflow_run": run | changes}, "workflow_run")

    def test_superseded_releases_skip_and_failures_never_start_a_deploy(self):
        with (
            patch.object(readiness, "github", return_value={"sha": "b" * 40}),
            patch.object(readiness, "select_revision") as selector,
        ):
            self.assertFalse(readiness.ready("a" * 40, True))
            selector.assert_not_called()
        with (
            patch.object(readiness, "github", return_value={"sha": "a" * 40}),
            patch.object(
                readiness, "select_revision", side_effect=ValueError("pending")
            ),
        ):
            self.assertFalse(readiness.ready("a" * 40, True))
            self.assertFalse(readiness.ready("a" * 40, False))

    def test_latest_rerun_attempt_invalidates_an_older_success(self):
        run = {
            "id": 1,
            "run_attempt": 1,
            "head_sha": "a" * 40,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        }
        responses = [{"status": "identical"}] + [
            {
                "workflow_runs": [
                    run,
                    run
                    | {"run_attempt": 2, "status": "in_progress", "conclusion": None},
                ]
            },
            *[{"workflow_runs": [run]}] * (len(release.REQUIRED_WORKFLOWS) - 1),
        ]
        with (
            patch.object(release, "github", side_effect=responses),
            self.assertRaises(ValueError),
        ):
            release.select_revision("a" * 40)

    def test_configuration_is_private_and_registry_token_overrides_recovery_pat(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = Path.cwd()
            config = root / "infra/ansible/inventories/prod/group_vars/all"
            config.mkdir(parents=True)
            values = dict.fromkeys(secrets.FILES, "synthetic-value") | {
                "OFFKEY_PROD_VAULT": "$ANSIBLE_VAULT;1.1;AES256\nfixture",
                "OFFKEY_DEPLOY_DIRECTORY": str(root / "private"),
                "GITHUB_ACTOR": "fixture-owner",
                "GH_TOKEN": "fixture-short-lived-token",
            }
            try:
                os.chdir(root)
                with patch.dict(os.environ, values):
                    secrets.main()
                for path in (root / "private").iterdir():
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual((root / "private").stat().st_mode & 0o777, 0o700)
                self.assertTrue((config / "vault.yml").is_symlink())
                self.assertEqual(
                    json.loads((root / "private/registry.json").read_text()),
                    {
                        "ghcr_username": "fixture-owner",
                        "ghcr_token": "fixture-short-lived-token",
                    },
                )
            finally:
                os.chdir(original)

    def test_missing_or_plaintext_vault_writes_no_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            values = dict.fromkeys(secrets.FILES, "fixture") | {
                "OFFKEY_DEPLOY_DIRECTORY": str(Path(directory) / "private")
            }
            with patch.dict(os.environ, values), self.assertRaises(SystemExit):
                secrets.main()
            self.assertFalse((Path(directory) / "private").exists())

    def test_release_job_preserves_literal_configuration_and_keeps_it_out_of_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bin").mkdir()
            docker = root / "bin/docker"
            docker.write_text(
                f"#!{sys.executable}\nimport json, pathlib, sys\n"
                f"with pathlib.Path({str(root / 'arguments')!r}).open('a') as log: log.write(json.dumps(sys.argv[1:]) + '\\n')\n"
                "print('CLI initialization')\n"
                "print(json.dumps({'phase': 'complete'}))\n"
            )
            docker.chmod(0o755)
            password = 'fixture=$literal"quoted\nsecond=line'
            playbook = root / "job.yml"
            playbook.write_text(
                yaml.safe_dump(
                    [
                        {
                            "hosts": "localhost",
                            "gather_facts": False,
                            "become": False,
                            "vars": {
                                "stack_name": "off-key",
                                "tactic_image": "fixture/tactic@sha256:abc",
                                "release": {"application_revision": "a" * 40},
                                "stack_compose_model": {
                                    "services": {
                                        "tactic": {
                                            "environment": {
                                                "POSTGRES_PASSWORD": password,
                                                "TACTIC_DOCKER_API_URL": "http://socket-proxy",
                                            }
                                        }
                                    }
                                },
                            },
                            "tasks": [
                                {
                                    "include_tasks": str(
                                        ROOT
                                        / "ansible/roles/stack_deploy/tasks/monitor_job.yml"
                                    ),
                                    "vars": {"monitor_action": "status"},
                                },
                                {
                                    "assert": {
                                        "that": "release_job_output.phase == 'complete'"
                                    }
                                },
                            ],
                        }
                    ]
                )
            )
            result = ansible(
                "playbook",
                "-i",
                "localhost,",
                "-c",
                "local",
                str(playbook),
                env=os.environ
                | {
                    "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
                    "ANSIBLE_CONFIG": str(ROOT / "ansible/ansible.cfg"),
                },
            )
            arguments = json.loads((root / "arguments").read_text())
            self.assertIn(f"POSTGRES_PASSWORD={password}", arguments)
            self.assertIn(
                "TACTIC_DOCKER_API_URL=unix:///var/run/docker.sock", arguments
            )
            self.assertIn(
                "type=bind,src=/var/run/docker.sock,dst=/var/run/docker.sock", arguments
            )
            self.assertEqual(
                arguments[-4:],
                ["-m", "off_key_tactic_middleware.deployment", "status", "a" * 40],
            )
            self.assertNotIn(password, result.stdout + result.stderr)

    def test_documentation_commit_cannot_hide_unreleased_runtime_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            playbook = root / "infra/ansible/deployment-needed.yml"
            playbook.parent.mkdir(parents=True)
            playbook.write_text((ROOT / "ansible/deployment-needed.yml").read_text())
            (root / "backend").mkdir()
            runtime = root / "backend/runtime.txt"
            runtime.write_text("old runtime\n")
            run("git", "init", "-q", cwd=root)
            run("git", "add", ".", cwd=root)
            commit = [
                "git",
                "-c",
                "user.name=Release Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-qam",
            ]
            run(*commit, "initial release", cwd=root)
            initial = run("git", "rev-parse", "HEAD", cwd=root).stdout.strip()
            runtime.write_text("new runtime\n")
            run(*commit, "runtime change", cwd=root)
            runtime_revision = run("git", "rev-parse", "HEAD", cwd=root).stdout.strip()
            (root / "docs").mkdir()
            (root / "docs/guide.md").write_text("Documentation change\n")
            run("git", "add", ".", cwd=root)
            run(*commit, "documentation change", cwd=root)
            target = run("git", "rev-parse", "HEAD", cwd=root).stdout.strip()
            stack = root / "stack"
            stack.mkdir()
            record = stack / "release.json"
            inventory = root / "inventory.yml"
            inventory.write_text(
                yaml.safe_dump(
                    {
                        "all": {
                            "vars": {
                                "ansible_connection": "local",
                                "ansible_become": False,
                                "ansible_python_interpreter": sys.executable,
                                "stack_dir": str(stack),
                                "deployment_decision_file": str(root / "decision"),
                            },
                            "children": {"swarm_manager": {"hosts": {"manager": {}}}},
                        }
                    }
                )
            )
            for verified, decision in [
                (initial, "yes"),
                (runtime_revision, "no"),
                (None, "yes"),
            ]:
                with self.subTest(verified=verified):
                    if verified is None:
                        record.unlink()
                    else:
                        record.write_text(
                            json.dumps({"application_revision": verified})
                        )
                    ansible(
                        "playbook",
                        "-i",
                        str(inventory),
                        str(playbook),
                        env=os.environ
                        | {
                            "ANSIBLE_CONFIG": str(ROOT / "ansible/ansible.cfg"),
                            "OFFKEY_RELEASE_REVISION": target,
                        },
                    )
                    self.assertEqual((root / "decision").read_text(), decision)
