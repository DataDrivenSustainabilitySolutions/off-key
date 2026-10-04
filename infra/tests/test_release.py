"""Release identity and readiness failures that public HTTP alone cannot detect."""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml
from jinja2 import Environment
from support import ROOT, ansible, run


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


application = load("check_application")
swarm = load("check_swarm")
release = load("pin_release")


class ReleaseTests(unittest.TestCase):
    def test_latest_release_requires_all_workflows_and_uses_main_commit_order(self):
        newest, eligible, older = (letter * 40 for letter in "abc")
        responses = [[{"sha": sha} for sha in (newest, eligible, older)]]
        for workflow in release.REQUIRED_WORKFLOWS:
            runs = [
                {
                    "id": number,
                    "run_attempt": 1,
                    "head_sha": sha,
                    "head_branch": "main",
                    "event": "push",
                    "status": "completed",
                    "conclusion": "success",
                }
                for number, sha in enumerate((newest, eligible, older), start=1)
            ]
            if workflow == "deployment-smoke.yml":
                # A later failed run invalidates the older success on the newest commit.
                runs.append(runs[0] | {"id": 4, "conclusion": "failure"})
            responses.append({"workflow_runs": runs})
        with (
            patch.object(release, "github", side_effect=responses) as github,
            redirect_stderr(StringIO()),
        ):
            self.assertEqual(release.select_revision("latest"), eligible)
        self.assertEqual(github.call_count, 1 + len(release.REQUIRED_WORKFLOWS))
        for call in github.call_args_list[1:]:
            self.assertIn("branch=main&event=push", call.args[0])

    def test_explicit_rollback_requires_successful_main_push_workflows(self):
        revision = "a" * 40
        successful_run = {
            "id": 1,
            "run_attempt": 1,
            "head_sha": revision,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        }
        with patch.object(
            release,
            "github",
            return_value={"status": "ahead", "workflow_runs": [successful_run]},
        ) as github:
            self.assertEqual(release.select_revision(revision), revision)
        self.assertEqual(github.call_count, 1 + len(release.REQUIRED_WORKFLOWS))
        self.assertTrue(
            all(
                f"head_sha={revision}" in call.args[0]
                for call in github.call_args_list[1:]
            )
        )
        for changes in (
            {"status": "in_progress", "conclusion": None},
            {"conclusion": "failure"},
            {"event": "pull_request"},
            {"head_branch": "feature"},
            {"head_sha": "b" * 40},
        ):
            with (
                self.subTest(changes=changes),
                patch.object(
                    release,
                    "github",
                    side_effect=[
                        {"status": "ahead"},
                        {"workflow_runs": [successful_run]},
                        {"workflow_runs": [successful_run | changes]},
                        *[{"workflow_runs": [successful_run]}]
                        * (len(release.REQUIRED_WORKFLOWS) - 2),
                    ],
                ),
                self.assertRaisesRegex(ValueError, "No eligible release"),
            ):
                release.select_revision(revision)

    def test_release_selection_fails_closed(self):
        with patch.object(release, "github") as github:
            with self.assertRaisesRegex(ValueError, "full lowercase commit SHA"):
                release.select_revision("main&status=success")
            github.assert_not_called()
        with (
            patch.object(
                release,
                "github",
                side_effect=[
                    [{"sha": "a" * 40}],
                    *[{"workflow_runs": []}] * len(release.REQUIRED_WORKFLOWS),
                ],
            ),
            self.assertRaisesRegex(ValueError, "No eligible release"),
        ):
            release.select_revision("latest")

    def test_stdout_resolves_application_images_without_changing_platform_or_manifest(
        self,
    ):
        document = json.loads(release.RELEASE.read_text())
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "release.yml"
            original = json.dumps(document)
            manifest.write_text(original)
            output = StringIO()
            with (
                patch.object(release, "RELEASE", manifest),
                patch.object(sys, "argv", ["pin_release.py", "--stdout"]),
                patch.object(release, "select_revision", return_value="a" * 40),
                patch.object(
                    release, "pin", side_effect=lambda ref, sha: ref + "-resolved"
                ) as pin,
                redirect_stdout(output),
            ):
                release.main()
            resolved = json.loads(output.getvalue())["release"]
            self.assertEqual(resolved["application_revision"], "a" * 40)
            self.assertEqual(pin.call_count, 6)
            for name, reference in document["release"]["images"].items():
                expected = (
                    reference + "-resolved"
                    if name in release.APPLICATION_IMAGES
                    else reference
                )
                self.assertEqual(resolved["images"][name], expected)
            self.assertEqual(manifest.read_text(), original)
            with (
                patch.object(release, "RELEASE", manifest),
                patch.object(sys, "argv", ["pin_release.py"]),
                patch.object(release, "select_revision", return_value="a" * 40),
                patch.object(
                    release,
                    "pin",
                    side_effect=["resolved", ValueError("missing image")],
                ),
                self.assertRaisesRegex(ValueError, "missing image"),
            ):
                release.main()
            self.assertEqual(manifest.read_text(), original)

    def test_selected_release_reaches_workers_in_later_plays(self):
        document = json.loads(release.RELEASE.read_text())
        document["release"]["application_revision"] = "a" * 40
        document["release"]["images"]["mqtt_radar"] = "example/radar@sha256:" + "b" * 64
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "infra/ansible").mkdir(parents=True)
            (root / "infra/scripts").mkdir()
            (root / "bin").mkdir()
            (root / ".gitignore").write_text("selections\ndocker-config-path\n")
            (root / "infra/scripts/pin_release.py").write_text(
                "import base64, json, os, pathlib, sys\n"
                "assert sys.argv[1:] == ['latest', '--stdout']\n"
                "config = json.loads(pathlib.Path(os.environ['DOCKER_CONFIG'], 'config.json').read_text())\n"
                "assert base64.b64decode(config['auths']['ghcr.io']['auth']) == b'fixture:fixture-token'\n"
                "assert pathlib.Path(os.environ['DOCKER_CONFIG'], 'config.json').stat().st_mode & 0o777 == 0o600\n"
                f"pathlib.Path({str(root / 'docker-config-path')!r}).write_text(os.environ['DOCKER_CONFIG'])\n"
                "if os.environ.get('RELEASE_FIXTURE_FAIL'): sys.exit('fixture registry failure')\n"
                f"with pathlib.Path({str(root / 'selections')!r}).open('a') as log: log.write('selected\\n')\n"
                "document = " + repr(document) + "\n"
                "import subprocess\n"
                "document['release']['application_revision'] = subprocess.check_output(['git', '-C', str(pathlib.Path(__file__).parents[2]), 'rev-parse', 'HEAD'], text=True).strip()\n"
                "print(json.dumps(document))\n"
            )
            docker = root / "bin/docker"
            docker.write_text(
                f"#!{sys.executable}\nimport sys\n"
                "assert sys.argv[1:4] == ['service', 'inspect', 'off-key_frontend']\n"
                f"print({document['release']['images']['frontend']!r})\n"
            )
            docker.chmod(0o755)
            inventory = root / "inventory.yml"
            inventory.write_text(
                yaml.safe_dump(
                    {
                        "all": {
                            "vars": {
                                "ansible_connection": "local",
                                "ansible_python_interpreter": sys.executable,
                                "ghcr_username": "fixture",
                                "ghcr_token": "fixture-token",
                            },
                            "children": {
                                "swarm_manager": {
                                    "hosts": {"manager1": {}, "manager2": {}}
                                },
                                "swarm_backend": {"hosts": {"worker": {}}},
                            },
                        }
                    }
                )
            )
            variables = [
                str(release.RELEASE),
                str(ROOT / "ansible/inventories/prod/group_vars/all/vars.yml"),
            ]
            playbook = root / "infra/ansible/test.yml"
            playbook.write_text(
                yaml.safe_dump(
                    [
                        {
                            "hosts": "swarm_manager",
                            "gather_facts": False,
                            "become": False,
                            "any_errors_fatal": True,
                            "vars_files": variables,
                            "tasks": [
                                {
                                    "include_tasks": str(
                                        ROOT
                                        / "ansible/roles/stack_prepare/tasks/release.yml"
                                    )
                                },
                            ],
                        },
                        {
                            "hosts": "all",
                            "gather_facts": False,
                            "become": False,
                            "vars_files": variables,
                            "tasks": [
                                {
                                    "assert": {
                                        "that": [
                                            "release.application_revision == hostvars['manager1'].infrastructure_revision.stdout",
                                            f"mqtt_radar_image == '{document['release']['images']['mqtt_radar']}'",
                                        ]
                                    }
                                }
                            ],
                        },
                    ]
                )
            )
            run("git", "init", "-q", cwd=root)
            run("git", "add", ".", cwd=root)
            run(
                "git",
                "-c",
                "user.name=Release Test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-qm",
                "test fixture",
                cwd=root,
            )
            env = os.environ | {
                "PATH": f"{root / 'bin'}:{os.environ['PATH']}",
                "ANSIBLE_CONFIG": str(ROOT / "ansible/ansible.cfg"),
                "OFFKEY_RELEASE_REVISION": "latest",
            }
            ansible("playbook", "-i", str(inventory), str(playbook), env=env)
            self.assertEqual((root / "selections").read_text(), "selected\n")
            self.assertFalse(Path((root / "docker-config-path").read_text()).exists())
            failed = ansible(
                "playbook",
                "-i",
                str(inventory),
                str(playbook),
                env=env | {"RELEASE_FIXTURE_FAIL": "1"},
                check=False,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("fixture registry failure", failed.stdout)
            self.assertNotIn("PLAY [all]", failed.stdout)
            self.assertNotIn("fixture-token", failed.stdout + failed.stderr)
            self.assertFalse(Path((root / "docker-config-path").read_text()).exists())

    def test_shell_probes_are_valid_jinja_templates(self):
        tasks = yaml.safe_load(
            (ROOT / "ansible/roles/stack_deploy/tasks/verify.yml").read_text()
        )
        for task in tasks[0]["block"]:
            if "shell" in task:
                Environment().parse(task["shell"])

    def test_pin_validates_revision_against_the_digest_not_the_tag(self):
        revision = "a" * 40
        digest = "sha256:" + "b" * 64
        with patch.object(
            release,
            "inspect",
            side_effect=[
                {"digest": digest},
                {
                    "architecture": "amd64",
                    "config": {
                        "Labels": {"org.opencontainers.image.revision": revision}
                    },
                },
            ],
        ) as inspect:
            pinned = release.pin("ghcr.io/example/api:sha-old@sha256:old", revision)
        self.assertEqual(pinned, f"ghcr.io/example/api:sha-aaaaaaa@{digest}")
        self.assertEqual(inspect.call_args.args, (pinned, "Image"))
        with (
            patch.object(
                release,
                "inspect",
                side_effect=[{"digest": digest}, {"architecture": "amd64"}],
            ),
            self.assertRaisesRegex(ValueError, "belongs to"),
        ):
            release.pin("ghcr.io/example/api:latest", revision)

    def test_convergence_probe_reaches_docker_with_supported_cli_options(self):
        # Exercise the real CLI parser without connecting to any Docker daemon.
        with tempfile.TemporaryDirectory() as directory:
            socket = Path(directory) / "absent-docker.sock"
            env = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith("DOCKER_")
            }
            env["DOCKER_CONFIG"] = directory
            env["DOCKER_HOST"] = f"unix://{socket}"
            result = run(
                sys.executable,
                str(ROOT / "scripts/check_swarm.py"),
                "off-key-test",
                "{}",
                env=env,
                check=False,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("unknown flag", result.stderr)
        self.assertIn(str(socket), result.stderr)

    def test_convergence_rejects_rollback_missing_tasks_and_wrong_release(self):
        image = "example/api@sha256:" + "b" * 64
        service = {
            "Spec": {
                "Name": "off-key_api",
                "Mode": {"Replicated": {"Replicas": 1}},
                "TaskTemplate": {"ContainerSpec": {"Image": image}},
            },
            "UpdateStatus": {"State": "completed"},
        }
        replicas = {"off-key_api": "1/1"}
        expected = {"off-key_api": {"image": image, "replicas": 1}}
        swarm.check_services([service], expected, replicas)
        for changes in ({"UpdateStatus": {"State": "rollback_completed"}},):
            with self.assertRaises(ValueError):
                swarm.check_services([service | changes], expected, replicas)
        with self.assertRaisesRegex(ValueError, "tasks running"):
            swarm.check_services([service], expected, {"off-key_api": "0/1"})
        with self.assertRaisesRegex(ValueError, "intended release"):
            swarm.check_services(
                [service],
                {"off-key_api": {"image": "other@sha256:" + "c" * 64, "replicas": 1}},
                replicas,
            )
        with self.assertRaises(ValueError):
            swarm.check_services([], expected, {})

    def test_convergence_requires_the_exact_service_image_and_replica_plan(self):
        images = {
            "api": "example/api@sha256:" + "a" * 64,
            "frontend": "example/frontend@sha256:" + "b" * 64,
        }
        expected = {
            f"off-key_{name}": {"image": image, "replicas": 1}
            for name, image in images.items()
        }
        services = [
            {
                "Spec": {
                    "Name": name,
                    "Mode": {"Replicated": {"Replicas": 1}},
                    "TaskTemplate": {"ContainerSpec": {"Image": target["image"]}},
                }
            }
            for name, target in expected.items()
        ]
        replicas = dict.fromkeys(expected, "1/1")
        swarm.check_services(services, expected, replicas)
        with self.assertRaisesRegex(ValueError, "missing=.*off-key_frontend"):
            swarm.check_services(services[:1], expected, replicas)
        swapped = deepcopy(services)
        swapped[0]["Spec"]["TaskTemplate"]["ContainerSpec"]["Image"] = images[
            "frontend"
        ]
        with self.assertRaisesRegex(ValueError, "off-key_api.*image"):
            swarm.check_services(swapped, expected, replicas)
        with self.assertRaisesRegex(ValueError, "expected 1"):
            swarm.check_services(services, expected, replicas | {"off-key_api": "0/0"})
        extra = deepcopy(services[0])
        extra["Spec"]["Name"] = "off-key_orphan"
        with self.assertRaisesRegex(ValueError, "unexpected=.*off-key_orphan"):
            swarm.check_services(services + [extra], expected, replicas)

    def test_readiness_accepts_offline_brokers_but_requires_fresh_workers_and_applied_routes(
        self,
    ):
        now = datetime.now(timezone.utc)
        selected = []
        snapshot = SimpleNamespace(
            revision=4,
            catalog=SimpleNamespace(
                sources=[
                    SimpleNamespace(
                        id="broker", label="Yard", host="yard.ts.net", port=1883
                    )
                ],
                streams=lambda **kwargs: selected,
            ),
            collection={
                "revision": 4,
                "status": "applied",
                "checked_at": now.isoformat(),
            },
            ingress={
                "revision": 4,
                "status": "applied",
                "checked_at": now.isoformat(),
                "sources": {"broker": {"status": "connected", "configured": True}},
            },
        )
        with redirect_stdout(StringIO()) as output:
            self.assertEqual(
                application.check_collection(snapshot, now)["selected_sensors"], 0
            )
            selected.append(SimpleNamespace(source_id="broker"))
            self.assertEqual(
                application.check_collection(snapshot, now)["selected_sensors"], 1
            )
        self.assertEqual(output.getvalue(), "")
        snapshot.ingress["sources"]["broker"]["status"] = "connecting"
        selected.append(SimpleNamespace(source_id="broker"))
        with redirect_stdout(StringIO()) as output:
            self.assertEqual(
                application.check_collection(snapshot, now)["selected_sensors"], 2
            )
        self.assertEqual(output.getvalue().count("WARNING:"), 1)
        self.assertIn("Yard (yard.ts.net:1883) is not connected", output.getvalue())
        self.assertIn("ingress route is applied", output.getvalue())
        for changes in (
            {"ingress": snapshot.ingress | {"sources": {}}},
            {
                "ingress": snapshot.ingress
                | {"sources": {"broker": {"status": "connected"}}}
            },
            {
                "ingress": snapshot.ingress
                | {"sources": {"broker": {"status": "connecting", "configured": False}}}
            },
            {
                "ingress": snapshot.ingress
                | {"sources": {"broker": {"status": "paused", "configured": True}}}
            },
            {
                "ingress": snapshot.ingress
                | {"sources": {"broker": {"status": "error", "configured": True}}}
            },
            {
                "collection": snapshot.collection
                | {"checked_at": (now - timedelta(seconds=31)).isoformat()}
            },
            {"collection": snapshot.collection | {"revision": 3}},
            {"ingress": snapshot.ingress | {"status": "error"}},
        ):
            broken = deepcopy(snapshot)
            for key, value in changes.items():
                setattr(broken, key, value)
            with self.assertRaises(ValueError):
                application.check_collection(broken, now)
        with self.assertRaisesRegex(ValueError, "disabled"):
            application.check_collection(snapshot, now, ingress_enabled=False)

    def test_new_database_needs_no_catalog_row_before_the_first_ui_save(self):
        snapshot = SimpleNamespace(
            revision=0,
            catalog=SimpleNamespace(sources=[], streams=lambda **kwargs: []),
            collection={},
            ingress={},
        )
        self.assertEqual(
            application.check_collection(snapshot, datetime.now(timezone.utc)),
            {"revision": 0, "selected_sensors": 0},
        )
        snapshot.revision = 1
        with self.assertRaisesRegex(ValueError, "not applied"):
            application.check_collection(snapshot, datetime.now(timezone.utc))

    def test_runtime_worker_created_during_deploy_cannot_escape_final_verification(
        self,
    ):
        image = "example/api@sha256:" + "b" * 64
        service = {
            "Spec": {
                "Name": "off-key_api",
                "Mode": {"Replicated": {"Replicas": 1}},
                "TaskTemplate": {"ContainerSpec": {"Image": image}},
            }
        }
        old_radar = {
            "Spec": {
                "Name": "radar-new",
                "Labels": {"managed_by": "tactic", "service_type": "radar"},
                "TaskTemplate": {"ContainerSpec": {"Image": "example/radar:latest"}},
            }
        }
        stopped_radar = deepcopy(old_radar)
        stopped_radar["Spec"]["TaskTemplate"]["ContainerSpec"]["Image"] = image
        stopped_radar["Spec"]["Mode"] = {"Replicated": {"Replicas": 0}}
        for radar, replicas, error in [
            (old_radar, "1/1", "recreate this RADAR"),
            (stopped_radar, "0/0", "expected 1"),
        ]:
            radar_row = {"ID": "radar-id", "Name": "radar-new", "Replicas": replicas}
            with (
                self.subTest(replicas=replicas),
                patch.object(
                    swarm.sys,
                    "argv",
                    ["check_swarm.py", "off-key", "model.json", image],
                ),
                patch.object(
                    swarm.Path,
                    "read_text",
                    return_value=json.dumps({"services": {"api": {"image": image}}}),
                ),
                patch.object(
                    swarm.subprocess,
                    "check_output",
                    side_effect=[
                        "\n".join(
                            json.dumps(row)
                            for row in [
                                {
                                    "ID": "api-id",
                                    "Name": "off-key_api",
                                    "Replicas": "1/1",
                                },
                                radar_row,
                            ]
                        ),
                        json.dumps([service, radar]),
                        json.dumps(radar_row),
                        json.dumps([radar]),
                    ],
                ),
                self.assertRaisesRegex(ValueError, error),
            ):
                swarm.main()
