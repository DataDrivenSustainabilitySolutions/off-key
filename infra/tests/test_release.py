"""Release identity and readiness failures that public HTTP alone cannot detect."""

import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml
from jinja2 import Environment
from support import ROOT, ansible, load_script, run

application = load_script("check_application")
swarm = load_script("check_swarm")
release = load_script("pin_release")


class ReleaseTests(unittest.TestCase):
    def test_ci_completion_is_the_only_automatic_release_trigger(self):
        workflows = ROOT.parent / ".github/workflows"
        deployment = yaml.load(
            (workflows / "deploy-production.yml").read_text(), Loader=yaml.BaseLoader
        )
        trigger = deployment["on"]["workflow_run"]
        self.assertIn("completed", trigger["types"])
        self.assertIn("main", trigger["branches"])
        gate = yaml.load(
            (workflows / release.RELEASE_WORKFLOW).read_text(), Loader=yaml.BaseLoader
        )
        self.assertEqual(trigger["workflows"], [gate["name"]])

    def test_release_workflow_runs_on_every_main_push(self):
        workflow = yaml.load(
            (ROOT.parent / ".github/workflows" / release.RELEASE_WORKFLOW).read_text(),
            Loader=yaml.BaseLoader,
        )
        push = workflow["on"]["push"]
        self.assertIn("main", push["branches"])
        self.assertNotIn("paths", push)
        self.assertNotIn("paths-ignore", push)

    def test_latest_release_requires_ci_and_uses_main_commit_order(self):
        newest, eligible, older = (letter * 40 for letter in "abc")
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
        # A later failed run invalidates the older success on the newest commit.
        runs.append(runs[0] | {"id": 4, "conclusion": "failure"})
        responses = [
            [{"sha": sha} for sha in (newest, eligible, older)],
            {"workflow_runs": runs},
        ]
        with (
            patch.object(release, "github", side_effect=responses) as github,
            redirect_stderr(StringIO()),
        ):
            self.assertEqual(release.select_revision("latest"), eligible)
        self.assertEqual(github.call_count, 2)
        self.assertIn(
            f"actions/workflows/{release.RELEASE_WORKFLOW}/runs?branch=main&event=push",
            github.call_args_list[1].args[0],
        )

    def test_explicit_rollback_requires_a_successful_main_push_run(self):
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
        self.assertEqual(github.call_count, 2)
        self.assertIn(f"head_sha={revision}", github.call_args_list[1].args[0])
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
                        {"workflow_runs": [successful_run | changes]},
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
                side_effect=[[{"sha": "a" * 40}], {"workflow_runs": []}],
            ),
            self.assertRaisesRegex(ValueError, "No eligible release"),
        ):
            release.select_revision("latest")

    def test_stdout_uses_tested_digests_without_resolving_mutable_tags(self):
        document = json.loads(release.RELEASE.read_text())
        tested = deepcopy(document["release"])
        tested["application_revision"] = "a" * 40
        for name in release.APPLICATION_IMAGES:
            repository = tested["images"][name].split("@", 1)[0].rsplit(":", 1)[0]
            tested["images"][name] = repository + "@sha256:" + "b" * 64
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "release.yml"
            original = json.dumps(document)
            manifest.write_text(original)
            output = StringIO()
            with (
                patch.object(release, "RELEASE", manifest),
                patch.object(sys, "argv", ["pin_release.py", "--stdout"]),
                patch.object(release, "select_revision", return_value="a" * 40),
                patch.object(release, "tested_release", return_value=tested),
                patch.object(release, "pin") as pin,
                redirect_stdout(output),
            ):
                release.main()
            self.assertEqual(json.loads(output.getvalue())["release"], tested)
            pin.assert_not_called()
            self.assertEqual(manifest.read_text(), original)
            with (
                patch.object(release, "RELEASE", manifest),
                patch.object(sys, "argv", ["pin_release.py"]),
                patch.object(release, "select_revision", return_value="a" * 40),
                patch.object(
                    release,
                    "tested_release",
                    side_effect=ValueError("missing tested artifact"),
                ),
                self.assertRaisesRegex(ValueError, "missing tested artifact"),
            ):
                release.main()
            self.assertEqual(manifest.read_text(), original)

    def test_tested_artifact_requires_matching_images_and_latest_main_run(self):
        revision = "a" * 40
        document = json.loads(release.RELEASE.read_text())
        document["release"]["application_revision"] = revision
        successful = {
            "id": 10,
            "run_attempt": 1,
            "head_sha": revision,
            "head_branch": "main",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
        }

        def download(args, **kwargs):
            self.assertEqual(args[:4], ["gh", "run", "download", "10"])
            Path(args[-1], "production-release.json").write_text(json.dumps(document))

        with (
            patch.object(
                release, "github", return_value={"workflow_runs": [successful]}
            ),
            patch.object(release.subprocess, "run", side_effect=download),
            patch.object(
                release,
                "inspect",
                return_value={
                    "architecture": "amd64",
                    "config": {
                        "Labels": {"org.opencontainers.image.revision": revision}
                    },
                },
            ) as inspect,
        ):
            self.assertEqual(release.tested_release(revision), document["release"])
            self.assertEqual(inspect.call_count, len(release.APPLICATION_IMAGES))
            for call in inspect.call_args_list:
                self.assertRegex(call.args[0], r"@sha256:[0-9a-f]{64}$")
            original = deepcopy(document)
            changes = [
                ("revision", "b" * 40),
                ("api", "ghcr.io/attacker/api@sha256:" + "b" * 64),
                (
                    "api",
                    "ghcr.io/datadrivensustainabilitysolutions/off-key-api-gateway:latest",
                ),
                (
                    "postgres",
                    original["release"]["images"]["postgres"].split("@", 1)[0]
                    + "@sha256:"
                    + "b" * 64,
                ),
            ]
            for name, value in changes:
                with (
                    self.subTest(change=name, value=value),
                    self.assertRaises(ValueError),
                ):
                    document = deepcopy(original)
                    if name == "revision":
                        document["release"]["application_revision"] = value
                    else:
                        document["release"]["images"][name] = value
                    release.tested_release(revision)
            document = deepcopy(original)
            with (
                patch.object(
                    release, "inspect", return_value={"architecture": "amd64"}
                ),
                self.assertRaisesRegex(ValueError, "belongs to"),
            ):
                release.tested_release(revision)
            for changes in (
                {"run_attempt": 2, "status": "in_progress", "conclusion": None},
                {"id": 11, "conclusion": "failure"},
                {"id": 11, "conclusion": "cancelled"},
            ):
                with (
                    self.subTest(run=changes),
                    patch.object(
                        release,
                        "github",
                        return_value={
                            "workflow_runs": [successful, successful | changes]
                        },
                    ),
                    self.assertRaisesRegex(ValueError, "No successful"),
                ):
                    release.tested_release(revision)

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

    def test_readiness_tasks_are_valid_jinja_templates(self):
        for name in (
            "verify.yml",
            "application_readiness.yml",
            "application_readiness_attempt.yml",
        ):
            with self.subTest(name=name):
                Environment().parse(
                    (ROOT / "ansible/roles/stack_deploy/tasks" / name).read_text()
                )

    def test_replaced_services_stop_right_before_the_release_applies(self):
        # A successor such as a node identity must never start beside the
        # service it replaces, so nothing may run between the two steps.
        tasks = yaml.safe_load(
            (ROOT / "ansible/roles/stack_deploy/tasks/main.yml").read_text()
        )
        included = [step.get("include_tasks") for step in tasks]
        position = included.index("replaced.yml")
        self.assertEqual(included[position + 1], "apply.yml")
        self.assertNotIn("apply.yml", included[:position])
        replaced = yaml.safe_load(
            (ROOT / "ansible/roles/stack_deploy/tasks/replaced.yml").read_text()
        )
        self.assertEqual(
            [step["name"] for step in replaced],
            [
                "List production stack services before replacing any",
                "Find replaced services that still exist",
                "Scale replaced services to zero",
                "Wait until the manager reports no live task of a replaced service",
                "Remove services a successor in this release replaces",
                "Confirm no container of a replaced service is left on any node",
            ],
        )
        Environment().parse(
            (ROOT / "ansible/roles/stack_deploy/tasks/replaced.yml").read_text()
        )

    def test_application_setup_runs_after_the_release_completes(self):
        # Catalogue writes are fenced while a release is open, and a step that
        # always fails inside the release would leave it unrecoverable by retry.
        tasks = yaml.safe_load(
            (ROOT / "ansible/roles/stack_deploy/tasks/verify.yml").read_text()
        )
        release_steps, *setup = tasks
        self.assertEqual(
            [step["name"] for step in release_steps["block"][-3:]],
            [
                "End application maintenance after successful verification",
                "Record the successfully verified release",
                "Remove the completed release operation record",
            ],
        )
        self.assertNotIn("bootstrap", json.dumps(release_steps))
        self.assertEqual(
            [step["include_tasks"] for step in setup],
            [
                "bootstrap_admin.yml",
                "bootstrap_demo_viewer.yml",
                "bootstrap_demo_catalogue.yml",
            ],
        )

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

    def test_new_database_needs_no_catalog_row_before_the_first_ui_save(self):
        snapshot = SimpleNamespace(
            revision=0,
            catalog=SimpleNamespace(
                document=SimpleNamespace(connections=[]),
                streams=lambda **kwargs: [],
            ),
            collection={},
            ingress={},
        )
        self.assertEqual(
            application.check_collection(snapshot, datetime.now(UTC)),
            {"revision": 0, "selected_sensors": 0},
        )
        snapshot.revision = 1
        with self.assertRaisesRegex(ValueError, "not applied"):
            application.check_collection(snapshot, datetime.now(UTC))

    def test_generic_readiness_checks_the_active_workers_and_selected_subscriptions(
        self,
    ):
        now = datetime.now(UTC)
        selected = [
            SimpleNamespace(source_id="broker"),
            SimpleNamespace(source_id="broker"),
        ]
        snapshot = SimpleNamespace(
            revision=9,
            catalog=SimpleNamespace(
                document=SimpleNamespace(
                    connections=[
                        SimpleNamespace(
                            id="broker", label="Lab", host="source-broker", port=1883
                        )
                    ]
                ),
                streams=lambda **kwargs: selected,
            ),
            collection={
                "revision": 9,
                "status": "applied",
                "checked_at": now.isoformat(),
            },
            ingress={
                "revision": 9,
                "status": "applied",
                "checked_at": now.isoformat(),
                "sources": {"broker": {"state": "connected", "message": None}},
            },
        )
        with redirect_stdout(StringIO()) as output:
            self.assertEqual(
                application.check_collection(snapshot, now),
                {"revision": 9, "selected_sensors": 2},
            )
        self.assertEqual(output.getvalue(), "")
        for phase in ("connecting", "waiting", "reconnecting"):
            snapshot.ingress["sources"]["broker"]["state"] = phase
            with redirect_stdout(StringIO()) as output:
                application.check_collection(snapshot, now)
            self.assertEqual(output.getvalue().count("WARNING:"), 1)
        for phase in ("blocked", "error", "disconnected", None):
            snapshot.ingress["sources"]["broker"]["state"] = phase
            with self.assertRaisesRegex(ValueError, "no applied ingress route"):
                application.check_collection(snapshot, now)
        snapshot.ingress["sources"]["broker"]["state"] = "connected"
        with self.assertRaisesRegex(ValueError, "disabled"):
            application.check_collection(snapshot, now, ingress_enabled=False)
        for worker in ("collection", "ingress"):
            for changes in (
                {"revision": 8},
                {"status": "error"},
                {"checked_at": (now - timedelta(seconds=31)).isoformat()},
            ):
                broken = deepcopy(snapshot)
                setattr(broken, worker, getattr(broken, worker) | changes)
                with self.assertRaises(ValueError):
                    application.check_collection(broken, now)
        selected.clear()
        snapshot.ingress["sources"] = {}
        self.assertEqual(application.check_collection(snapshot, now)["revision"], 9)
        snapshot.ingress["status"] = "error"
        with self.assertRaises(ValueError):
            application.check_collection(snapshot, now)

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
