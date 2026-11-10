"""Static releases must never skip a changed runtime or an unfinished recovery."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import yaml
from support import ROOT, ansible, load_script, run

static = load_script("static_release")


class StaticReleaseTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.model = {
            "services": {
                "api": {
                    "image": "api@sha256:old",
                    "environment": {"KEY_FILE": "secret"},
                },
                "tactic": {"image": "tactic@sha256:old", "environment": {}},
                "frontend": {"image": "frontend@sha256:old", "deploy": {"replicas": 1}},
                "docs": {"image": "docs@sha256:old", "deploy": {"replicas": 1}},
            },
            "secrets": {"secret": {"external": True}},
        }
        self.specs = {
            name: {"Name": name, "TaskTemplate": service}
            for name, service in self.model["services"].items()
        }
        self.saved = {
            "version": 1,
            "revision": "a" * 40,
            "model": self.model,
            "specs": self.specs,
        }
        self.desired = deepcopy(self.model)
        for name in ("frontend", "docs"):
            self.desired["services"][name]["image"] = name + "@sha256:new"
        self.write(static.STATE, self.saved)
        self.write("release.json", {"application_revision": "a" * 40})
        self.write("deployment-model.json", self.desired)

    def write(self, name, value):
        (self.directory / name).write_text(json.dumps(value))

    def select(self, paths=None, specs=None):
        return static.decision(
            self.directory,
            "stack",
            ["frontend/src/App.tsx", "docs/index.md"] if paths is None else paths,
            self.specs if specs is None else specs,
        )

    def test_only_static_image_changes_can_use_the_unchanged_runtime(self):
        self.assertEqual(
            self.select(),
            {"frontend": "frontend@sha256:new", "docs": "docs@sha256:new"},
        )
        for change in (
            "backend",
            "secret",
            "frontend-config",
            "new-service",
            "network",
        ):
            with self.subTest(change=change):
                model = deepcopy(self.desired)
                if change == "backend":
                    model["services"]["api"]["image"] = "api@sha256:new"
                elif change == "secret":
                    model["secrets"]["secret"] = {"external": False}
                elif change == "frontend-config":
                    model["services"]["frontend"]["deploy"]["replicas"] = 2
                elif change == "new-service":
                    model["services"]["other"] = {"image": "other"}
                else:
                    model["networks"] = {"app": {"external": True}}
                self.write("deployment-model.json", model)
                self.assertEqual(self.select(), {})

    def test_source_changes_live_drift_and_pending_operations_force_full_cutover(self):
        for paths in (
            [],
            ["backend/app.py"],
            ["infra/ansible/deploy.yml"],
            ["new/file"],
            ["frontend/../backend/app.py"],
        ):
            with self.subTest(paths=paths):
                self.assertEqual(self.select(paths), {})
        drifted = deepcopy(self.specs)
        drifted["api"]["TaskTemplate"]["environment"]["KEY_FILE"] = "changed"
        self.assertEqual(self.select(specs=drifted), {})
        self.assertEqual(self.select(specs=self.specs | {"unexpected": {}}), {})
        for pending in ("recovery-pending.json", "release-maintenance.json"):
            (self.directory / pending).touch()
            self.assertEqual(self.select(), {})
            (self.directory / pending).unlink()
        self.write("release.json", {"application_revision": "b" * 40})
        self.assertEqual(self.select(), {})

    def test_missing_or_corrupt_baseline_and_unavailable_docker_disable_optimization(
        self,
    ):
        (self.directory / static.STATE).write_text("invalid")
        self.assertEqual(self.select(), {})
        (self.directory / static.STATE).unlink()
        self.assertEqual(self.select(), {})
        self.write(static.STATE, self.saved)
        with patch.object(
            static, "specs", side_effect=subprocess.CalledProcessError(1, "docker")
        ):
            self.assertEqual(
                static.decision(self.directory, "stack", ["frontend/app.tsx"]), {}
            )

    def test_apply_rechecks_drift_and_only_updates_selected_static_services(self):
        self.write("release-maintenance.json", {"revision": "b" * 40})
        original = (self.directory / "release.json").read_bytes()
        args = [
            "static_release.py",
            "apply",
            str(self.directory),
            "stack",
            '["frontend/app.tsx", "docs/index.md"]',
            "--revision",
            "b" * 40,
            "--baseline-revision",
            "a" * 40,
        ]
        with (
            patch.object(sys, "argv", args),
            patch.object(static, "specs", return_value=self.specs),
            patch.object(static, "docker") as docker,
        ):
            static.main()
        self.assertEqual(
            [call.args for call in docker.call_args_list],
            [
                (
                    "service",
                    "update",
                    "--detach=false",
                    "--with-registry-auth",
                    "--image",
                    f"{name}@sha256:new",
                    f"stack_{name}",
                )
                for name in ("docs", "frontend")
            ],
        )
        self.assertEqual((self.directory / "release.json").read_bytes(), original)
        with (
            patch.object(sys, "argv", args),
            patch.object(static, "specs", return_value={}),
            patch.object(static, "docker") as docker,
        ):
            with self.assertRaises(SystemExit):
                static.main()
            docker.assert_not_called()

    def test_record_keeps_private_exact_model_and_specs_after_verification(self):
        self.write("release.json", {"application_revision": "b" * 40})
        with patch.object(static, "specs", return_value=self.specs):
            static.record(self.directory, "stack")
        saved = json.loads((self.directory / static.STATE).read_text())
        self.assertEqual(saved["revision"], "b" * 40)
        self.assertEqual(saved["model"], self.desired)
        self.assertEqual(saved["specs"], self.specs)
        self.assertEqual(os.stat(self.directory / static.STATE).st_mode & 0o777, 0o600)

    def test_only_the_owned_reservation_can_pass_the_final_static_recheck(self):
        self.write("release-maintenance.json", {"revision": "b" * 40})
        self.assertEqual(self.select(), {})
        self.assertEqual(
            static.decision(
                self.directory, "stack", ["frontend/app.tsx"], self.specs, "a" * 40
            ),
            {},
        )
        self.assertTrue(
            static.decision(
                self.directory, "stack", ["frontend/app.tsx"], self.specs, "b" * 40
            )
        )
        self.assertEqual(
            static.decision(
                self.directory,
                "stack",
                ["frontend/app.tsx"],
                self.specs,
                "b" * 40,
                "c" * 40,
            ),
            {},
        )
        (self.directory / "recovery-pending.json").touch()
        self.assertEqual(
            static.decision(
                self.directory, "stack", ["frontend/app.tsx"], self.specs, "b" * 40
            ),
            {},
        )

    def test_ansible_selects_static_only_after_the_source_and_database_guards(self):
        project = self.directory / "project"
        playbooks = project / "infra/ansible"
        playbooks.mkdir(parents=True)
        scripts = project / "infra/scripts"
        scripts.mkdir()
        (scripts / "static_release.py").write_text(
            (ROOT / "scripts/static_release.py").read_text()
        )
        (project / "frontend").mkdir()
        source = project / "frontend/app.tsx"
        source.write_text("before")

        def git(*args):
            return run(
                "git",
                "-c",
                "user.name=T",
                "-c",
                "user.email=t@example.invalid",
                *args,
                cwd=project,
            ).stdout.strip()

        git("init", "-q")
        git("add", "-A")
        git("commit", "-qm", "baseline")
        previous = git("rev-parse", "HEAD")
        source.write_text("after")
        git("commit", "-qam", "frontend")
        target = git("rev-parse", "HEAD")
        self.write(static.STATE, self.saved | {"revision": previous})
        self.write("release.json", {"application_revision": previous})
        executable = self.directory / "docker"
        executable.write_text(
            f"#!{sys.executable}\n"
            + """
import json, os, sys
from pathlib import Path
a = sys.argv[1:]
if a[:2] == ['service', 'ls']:
    print('api frontend docs tactic')
elif a[:2] == ['service', 'inspect']:
    saved = json.loads(Path(os.environ['STATIC_TEST_BASELINE']).read_text())
    print(json.dumps([{'Spec': spec} for spec in saved['specs'].values()]))
elif a[0] == 'run':
    print(json.dumps({'phase': os.environ['STATIC_TEST_PHASE']}))
else:
    sys.exit('Unexpected Docker command')
"""
        )
        executable.chmod(0o755)
        playbook = playbooks / "select.yml"
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
                                    "name": "stack_deploy",
                                    "tasks_from": "static_select",
                                }
                            },
                            {
                                "assert": {
                                    "that": "release_static_only == expected_static"
                                }
                            },
                        ],
                    }
                ]
            )
        )
        variables = {
            "ansible_become": False,
            "ansible_python_interpreter": sys.executable,
            "stack_dir": str(self.directory),
            "stack_name": "stack",
            "stack_compose_model": self.desired,
            "tactic_image": "tactic@sha256:old",
            "release": {"application_revision": target},
        }
        for phase in ("complete", "quiescing"):
            ansible(
                "playbook",
                "-i",
                "localhost,",
                playbook,
                "-e",
                json.dumps(variables | {"expected_static": phase == "complete"}),
                env=os.environ
                | {
                    "PATH": str(self.directory) + os.pathsep + os.environ["PATH"],
                    "ANSIBLE_CONFIG": str(ROOT / "ansible/ansible.cfg"),
                    "ANSIBLE_ROLES_PATH": str(ROOT / "ansible/roles"),
                    "STATIC_TEST_BASELINE": str(self.directory / static.STATE),
                    "STATIC_TEST_PHASE": phase,
                },
            )
