"""Exercise recovery orchestration against a local, stateful Docker CLI fixture."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from persistence_fixture import DOCKER, EMQX_DOCKER
from support import ROOT, ansible, run


class PersistenceTests(unittest.TestCase):
    def run_cutover(
        self, directory, *, persistent=True, extra_vars=None, **environment
    ):
        root = Path(directory)
        (root / "docker").write_text(f"#!{sys.executable}\n" + DOCKER)
        (root / "docker").chmod(0o755)
        (root / "stack").mkdir(exist_ok=True)
        if not (root / "state.json").exists():
            (root / "state.json").write_text(
                json.dumps(
                    {
                        "replicas": {
                            "off-key_postgres": 1,
                            "off-key_api": 1,
                            "radar-runtime": 2,
                        },
                        "deployed": False,
                        "persistent": not persistent,
                    }
                )
            )
        inventory = root / "inventory.yml"
        inventory.write_text(
            yaml.safe_dump(
                {
                    "all": {
                        "children": {
                            "swarm_manager": {
                                "hosts": {"localhost": {"ansible_connection": "local"}}
                            },
                        }
                    }
                }
            )
        )
        playbook = root / "cutover.yml"
        playbook.write_text(
            yaml.safe_dump(
                [
                    {
                        "hosts": "swarm_manager",
                        "gather_facts": False,
                        "tasks": [
                            {
                                "include_role": {
                                    "name": "stack_deploy",
                                    "tasks_from": "model",
                                }
                            },
                            {
                                "include_role": {
                                    "name": "stack_deploy",
                                    "tasks_from": "apply",
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
            "persistence_switch_confirm": True,
            "stack_name": "off-key",
            "stack_dir": str(root / "stack"),
            "stack_compose_files": [str(root / "stack/compose.yml")],
            "postgres_user": "fixture",
            "postgres_db": "fixture_db",
            "persist_postgres": persistent,
            "persistence_backup_dir": str(root / "backups"),
        } | (extra_vars or {})
        env = (
            os.environ
            | {
                "PATH": str(root) + os.pathsep + os.environ["PATH"],
                "DOCKER_FIXTURE": str(root),
                "ANSIBLE_CONFIG": str(ROOT / "ansible/ansible.cfg"),
                "PERSIST_POSTGRES": "1" if persistent else "0",
            }
            | environment
        )
        result = ansible(
            "playbook",
            "-i",
            str(inventory),
            str(playbook),
            "-e",
            json.dumps(variables),
            env=env,
            check=False,
        )
        commands = [
            json.loads(line)
            for line in (root / "commands.jsonl").read_text().splitlines()
        ]
        return result, json.loads((root / "state.json").read_text()), commands

    def test_cutover_restores_only_the_replacement_after_stopping_all_writers(self):
        for persistent in (True, False):
            with (
                self.subTest(persistent=persistent),
                tempfile.TemporaryDirectory() as directory,
            ):
                result, state, commands = self.run_cutover(
                    directory, persistent=persistent
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(
                    state["replicas"],
                    {"off-key_postgres": 1, "off-key_api": 1, "radar-runtime": 2},
                )
                restore = next(
                    command for command in commands if "pg_restore" in command
                )
                self.assertEqual(restore[1:3], ["-i", "replacement"])
                # A cutover restores its own fresh backup and keeps sessions.
                self.assertFalse(
                    any(
                        "session_version + 1" in part
                        for command in commands
                        for part in command
                    )
                )
                self.assertTrue(
                    list(
                        (Path(directory) / "backups/postgres").glob("*/fixture_db.dump")
                    )
                )
                # Only the control host keeps the dumps; the node's staging is gone.
                self.assertEqual(
                    list((Path(directory) / "stack/.backup").glob("**/*.dump")), []
                )
                self.assertFalse(
                    (Path(directory) / "stack/recovery-pending.json").exists()
                )
                # The stack's own writers are seen stopped before the runtime
                # workers are told to stop.
                stack_stop = commands.index(
                    ["service", "scale", "--detach", "off-key_api=0"]
                )
                worker_stop = commands.index(
                    ["service", "scale", "--detach", "radar-runtime=0"]
                )
                self.assertTrue(
                    any(
                        command[:3] == ["inspect", "--type", "task"]
                        and command[-1] == "off-key_api-task"
                        for command in commands[stack_stop:worker_stop]
                    )
                )
                # This model has no frontend, so each resumed service is awaited.
                self.assertIn(
                    ["service", "scale", "--detach=false", "off-key_api=1"], commands
                )

    def test_resumed_services_are_awaited_by_their_scale_or_the_backend_check(self):
        tasks = yaml.safe_load(
            (ROOT / "ansible/roles/stack_deploy/tasks/apply.yml").read_text()
        )[0]["block"]
        names = [task["name"] for task in tasks]
        resume = names.index(
            "Resume desired stack services after successful restoration"
        )
        check = names.index(
            "Serve backend contracts before activating the browser bundle"
        )
        # A resumed service is not awaited by its scale call only where the
        # backend convergence check that follows waits for it instead.
        self.assertIn(
            "--detach={{ ('frontend' in stack_compose_model.services) | lower }}",
            tasks[resume]["command"]["argv"],
        )
        self.assertLess(resume, check)
        self.assertEqual(
            tasks[check]["when"], "'frontend' in stack_compose_model.services"
        )
        self.assertEqual(
            tasks[check]["block"][0]["name"],
            "Wait for the intended backend images without accepting rollbacks",
        )
        self.assertIn("--backend-first", tasks[check]["block"][0]["command"]["argv"])

    def cutover_with_a_short_retry_budget(self, base, role, task_file, find_task):
        """Prepare a cutover on the canonical roles, with one retry budget shortened.

        The role that holds the task is copied and only that task's retries and
        delay change; every other role is the canonical one.
        """
        roles = base / "ansible/roles"
        roles.mkdir(parents=True)
        for source in (ROOT / "ansible/roles").iterdir():
            if source.name == role:
                shutil.copytree(source, roles / role)
            else:
                (roles / source.name).symlink_to(source)
        # The roles and the playbook read their scripts relative to themselves.
        (base / "scripts").symlink_to(ROOT / "scripts")
        path = roles / role / "tasks" / task_file
        tasks = yaml.safe_load(path.read_text())
        find_task(tasks).update(retries=1, delay=0)
        path.write_text(yaml.safe_dump(tasks))
        work = base / "work"
        work.mkdir()
        return work, {"ANSIBLE_ROLES_PATH": str(roles)}

    def test_runtime_workers_stop_only_after_the_stack_writers_have_stopped(self):
        replicas = {"off-key_postgres": 1, "off-key_api": 1, "radar-runtime": 2}
        worker_stop = ["service", "scale", "--detach", "radar-runtime=0"]
        for task_states in (["running", "shutdown"], ["running"]):
            with (
                self.subTest(task_states=task_states),
                tempfile.TemporaryDirectory() as directory,
            ):
                work, roles = self.cutover_with_a_short_retry_budget(
                    Path(directory),
                    "persistence_switch",
                    "wait_stopped.yml",
                    lambda tasks: tasks[0],
                )
                (work / "state.json").write_text(
                    json.dumps(
                        {
                            "replicas": replicas,
                            "deployed": False,
                            "persistent": False,
                            # The scale call returns while the API's task still runs.
                            "task_state_sequences": {"off-key_api": task_states},
                        }
                    )
                )
                result, state, commands = self.run_cutover(work, **roles)
                stack_stop = commands.index(
                    ["service", "scale", "--detach", "off-key_api=0"]
                )
                if task_states[-1] == "shutdown":
                    self.assertEqual(
                        result.returncode, 0, result.stdout + result.stderr
                    )
                    # The first look saw the API's task running. The workers were
                    # told to stop only after a second look saw it stopped.
                    looks = [
                        command
                        for command in commands[
                            stack_stop : commands.index(worker_stop)
                        ]
                        if command[:3] == ["inspect", "--type", "task"]
                        and command[-1] == "off-key_api-task"
                    ]
                    self.assertEqual(len(looks), 2)
                    continue
                # The API's task never stops: no worker is told to stop, no backup
                # runs beside the live writer and nothing is replaced.
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Wait for every task to stop", result.stdout)
                self.assertIn("original writers resumed", result.stdout)
                self.assertNotIn(worker_stop, commands)
                self.assertFalse(
                    any(
                        "pg_dump" in command
                        or "pg_dumpall" in command
                        or command[:2] == ["stack", "deploy"]
                        for command in commands
                    )
                )
                self.assertEqual(state["replicas"], replicas)
                self.assertFalse((work / "stack/recovery-pending.json").exists())

    def test_a_resumed_backend_that_does_not_converge_stops_the_deployment(self):
        check = "Wait for the intended backend images without accepting rollbacks"
        with tempfile.TemporaryDirectory() as directory:
            work, roles = self.cutover_with_a_short_retry_budget(
                Path(directory),
                "stack_deploy",
                "apply.yml",
                lambda tasks: next(
                    task
                    for task in tasks[0]["block"]
                    if task["name"]
                    == "Serve backend contracts before activating the browser bundle"
                )["block"][0],
            )
            (work / "state.json").write_text(
                json.dumps(
                    {
                        "replicas": {
                            "off-key_postgres": 1,
                            "off-key_api": 1,
                            "off-key_frontend": 1,
                            "radar-runtime": 2,
                        },
                        "deployed": False,
                        "persistent": False,
                    }
                )
            )
            result, state, commands = self.run_cutover(
                work,
                extra_vars={"release": {"images": {"mqtt_radar": "example/radar"}}},
                STALLED_SERVICE="off-key_api",
                **roles,
            )
            self.assertNotEqual(result.returncode, 0)
            # With a frontend in the model the scale call does not wait for the API,
            self.assertIn(
                ["service", "scale", "--detach=true", "off-key_api=1"], commands
            )
            # so the convergence check is what sees that its task never started.
            self.assertIn(f"Deployment stopped at '{check}'", result.stdout)
            self.assertIn("off-key_api: 0/1 tasks running, expected 1", result.stdout)
            # The browser bundle is not activated and the cutover stays open.
            self.assertEqual(
                sum(command[:2] == ["stack", "deploy"] for command in commands), 1
            )
            self.assertFalse((work / "stack/browser-cutover.json").exists())
            plan = json.loads((work / "stack/recovery-pending.json").read_text())
            self.assertEqual(plan["phase"], "restore")
            self.assertEqual(state["replicas"]["off-key_frontend"], 0)

    def test_restore_adds_the_foreign_keys_of_ordinary_tables_last(self):
        # The post-data entries of a backup as `pg_restore --list` prints them.
        index = "4201; 1259 18001 INDEX public idx_anomaly_timestamp_desc fixture"
        # pg_dump lists a comment directly after the entry it describes.
        on_index = "4206; 0 0 COMMENT public INDEX idx_anomaly_timestamp_desc fixture"
        to_hypertable = (
            "4202; 2606 18002 FK CONSTRAINT public anomaly_identity "
            "fk_anomaly_identity_anomaly fixture"
        )
        on_to_hypertable = (
            "4207; 0 0 COMMENT public CONSTRAINT fk_anomaly_identity_anomaly "
            "ON anomaly_identity fixture"
        )
        to_table = "4203; 2606 18003 FK CONSTRAINT public users users_role_fkey fixture"
        of_hypertable = (
            "4204; 2606 18004 FK CONSTRAINT public samples samples_device_fkey fixture"
        )
        on_of_hypertable = (
            "4208; 0 0 COMMENT public CONSTRAINT samples_device_fkey ON samples fixture"
        )
        of_chunk = (
            "4205; 2606 18005 FK CONSTRAINT _timescaledb_internal _hyper_4_5_chunk "
            "5_1_samples_device_fkey fixture"
        )
        timescaledb_tables = [
            "public anomalies",
            "public samples",
            "_timescaledb_internal _hyper_4_5_chunk",
        ]
        # A key that waits takes its comment along: the comment fails without the key.
        for ordinary in ([to_hypertable, on_to_hypertable, to_table], []):
            with (
                self.subTest(ordinary=ordinary),
                tempfile.TemporaryDirectory() as directory,
            ):
                as_dumped = [
                    "; Selected TOC Entries:",
                    index,
                    on_index,
                    of_hypertable,
                    on_of_hypertable,
                    of_chunk,
                ]
                result, _, commands = self.run_cutover(
                    directory,
                    RESTORE_ENTRIES="\n".join(as_dumped[:3] + ordinary + as_dumped[3:]),
                    TIMESCALEDB_TABLES="\n".join(timescaledb_tables),
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                root = Path(directory)
                self.assertEqual(
                    (root / "restore-first.list").read_text().splitlines(), as_dumped
                )
                steps = [
                    "post_restore"
                    if any("timescaledb_post_restore" in part for part in command)
                    else " ".join(
                        part
                        for part in command
                        if part.startswith(("--section", "--list", "PGOPTIONS", "/tmp"))
                    )
                    for command in commands
                    if "pg_restore" in command
                    or any("timescaledb_post_restore" in part for part in command)
                ]
                # TimescaleDB is active for the last entries alone, and the
                # background jobs stay stopped until every key is back.
                last = "PGOPTIONS=-c timescaledb.restoring=off /tmp/restore-last.list"
                self.assertEqual(
                    steps,
                    [
                        "--section=pre-data --section=data",
                        "--section=post-data --list",
                        "/tmp/restore-first.list",
                        *([last] if ordinary else []),
                        "post_restore",
                    ],
                )
                if ordinary:
                    self.assertEqual(
                        (root / "restore-last.list").read_text().splitlines(), ordinary
                    )
                else:
                    self.assertFalse((root / "restore-last.list").exists())

    def test_ephemeral_mount_must_be_unconfigured_and_image_defined(self):
        invalid_mounts = (
            {"CONFIGURED_MOUNT": "1"},
            {"IMAGE_VOLUMES": "{}"},
            {
                "CONTAINER_MOUNTS": json.dumps(
                    [
                        {
                            "Destination": "/var/lib/postgresql/data",
                            "Type": "bind",
                            "Source": "/data",
                        }
                    ]
                )
            },
            {
                "CONTAINER_MOUNTS": json.dumps(
                    [
                        {
                            "Destination": "/var/lib/postgresql/data",
                            "Type": "volume",
                            "Name": "off-key_postgres_data",
                        }
                    ]
                )
            },
        )
        for environment in invalid_mounts:
            with (
                self.subTest(environment=environment),
                tempfile.TemporaryDirectory() as directory,
            ):
                result, state, commands = self.run_cutover(
                    directory, persistent=False, **environment
                )
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(state["replicas"]["off-key_api"], 0)
                self.assertEqual(state["replicas"]["radar-runtime"], 0)
                self.assertFalse(any("pg_restore" in command for command in commands))
                self.assertTrue(
                    (Path(directory) / "stack/recovery-pending.json").exists()
                )

    def test_failed_restore_or_wrong_mount_never_resumes_writers(self):
        for failure in ("RESTORE_FAIL", "WRONG_MOUNT"):
            with (
                self.subTest(failure=failure),
                tempfile.TemporaryDirectory() as directory,
            ):
                result, state, commands = self.run_cutover(directory, **{failure: "1"})
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(state["replicas"]["off-key_api"], 0)
                self.assertEqual(state["replicas"]["radar-runtime"], 0)
                self.assertTrue(
                    (Path(directory) / "stack/recovery-pending.json").exists()
                )
                retried, retry_state, retry_commands = self.run_cutover(directory)
                self.assertNotEqual(retried.returncode, 0)
                self.assertIn("interrupted recovery", retried.stdout)
                self.assertEqual(retry_state["replicas"]["off-key_api"], 0)
                self.assertEqual(
                    sum(
                        command[:2] == ["stack", "deploy"] for command in retry_commands
                    ),
                    1,
                )
                if failure == "WRONG_MOUNT":
                    self.assertFalse(
                        any("pg_restore" in command for command in commands)
                    )

    def test_emqx_requires_a_successful_fresh_export_even_without_a_volume(self):
        for mode in ("fresh", "stale", "unready"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fixture = EMQX_DOCKER
                (root / "docker").write_text(f"#!{sys.executable}\n" + fixture)
                (root / "docker").chmod(0o755)
                (root / "state.json").write_text(
                    json.dumps(
                        {
                            "replicas": {"off-key_emqx-main": 1},
                            "deployed": False,
                        }
                    )
                )
                playbook = root / "backup.yml"
                playbook.write_text(
                    yaml.safe_dump(
                        [
                            {
                                "hosts": "localhost",
                                "gather_facts": False,
                                "tasks": [
                                    {
                                        "include_role": {
                                            "name": "persistence_switch",
                                            "tasks_from": "backup_emqx",
                                        }
                                    }
                                ],
                            }
                        ]
                    )
                )
                variables = {
                    "ansible_connection": "local",
                    "ansible_become": False,
                    "ansible_python_interpreter": sys.executable,
                    "persistence_switch_confirm": True,
                    "stack_name": "off-key",
                    "stack_dir": str(root / "stack"),
                    "persistence_run_ts": "fixture",
                    "persistence_backup_dir": str(root / "backups"),
                }
                env = os.environ | {
                    "PATH": str(root) + os.pathsep + os.environ["PATH"],
                    "DOCKER_FIXTURE": str(root),
                    "EXPORT_MODE": mode,
                    "ANSIBLE_CONFIG": str(ROOT / "ansible/ansible.cfg"),
                }
                result = ansible(
                    "playbook",
                    "-i",
                    "localhost,",
                    str(playbook),
                    "-e",
                    json.dumps(variables),
                    env=env,
                    check=False,
                )
                archive = root / "backups/emqx/fixture/emqx-export-fresh.tar.gz"
                if mode == "fresh":
                    self.assertEqual(
                        result.returncode, 0, result.stdout + result.stderr
                    )
                    self.assertTrue(archive.exists())
                else:
                    self.assertNotEqual(
                        result.returncode, 0, result.stdout + result.stderr
                    )
                    self.assertFalse(list((root / "backups").glob("**/*.tar.gz")))

    def test_public_restore_initialises_defaults_and_validates_before_stopping_services(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ansible").mkdir()
            playbook = root / "ansible/restore-stack-state.yml"
            playbook.write_text((ROOT / "ansible/restore-stack-state.yml").read_text())
            (playbook.parent / "validate-inventory.yml").write_text(
                (ROOT / "ansible/validate-inventory.yml").read_text()
            )
            timestamp = "20260807T120000Z"
            backup = root / "stack/state/prod/postgres" / timestamp
            backup.mkdir(parents=True)
            (backup / "roles.sql").write_text("-- fixture roles")
            (backup / "fixture_db.dump").write_text("fixture saved data")
            (root / "docker").write_text(f"#!{sys.executable}\n" + DOCKER)
            (root / "docker").chmod(0o755)
            (root / "state.json").write_text(
                json.dumps(
                    {
                        "replicas": {
                            "off-key_postgres": 1,
                            "off-key_api": 1,
                            "radar-runtime": 2,
                        },
                        "deployed": False,
                    }
                )
            )
            inventory = root / "inventory.yml"
            inventory.write_text(
                yaml.safe_dump(
                    {
                        "all": {
                            "children": {
                                "swarm_manager": {
                                    "hosts": {
                                        "localhost": {"ansible_connection": "local"}
                                    }
                                },
                            }
                        }
                    }
                )
            )
            variables = {
                "ansible_become": False,
                "ansible_python_interpreter": sys.executable,
                "offkey_env": "prod",
                "persistence_switch_confirm": True,
                "stack_name": "off-key",
                "postgres_user": "fixture",
                "postgres_db": "fixture_db",
                "stack_dir": str(root / "live-stack"),
            }
            env = os.environ | {
                "PATH": str(root) + os.pathsep + os.environ["PATH"],
                "DOCKER_FIXTURE": str(root),
                "MANUAL_RESTORE": "1",
                "ANSIBLE_CONFIG": str(ROOT / "ansible/ansible.cfg"),
            }
            result = ansible(
                "playbook",
                "-i",
                str(inventory),
                str(playbook),
                "-e",
                json.dumps(variables),
                env=env,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(timestamp, result.stdout)
            self.assertNotIn("is undefined", result.stdout)
            self.assertFalse((root / "commands.jsonl").exists())
            result = ansible(
                "playbook",
                "-i",
                str(inventory),
                str(playbook),
                "-e",
                json.dumps(
                    variables | {"restore_from": timestamp, "restore_services": "emqx"}
                ),
                env=env,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing or incomplete", result.stdout)
            self.assertFalse((root / "commands.jsonl").exists())
            legacy = ansible(
                "playbook",
                "-i",
                str(inventory),
                str(playbook),
                "-e",
                json.dumps(
                    variables
                    | {"restore_from": timestamp, "restore_services": "postgres"}
                ),
                env=env,
                check=False,
            )
            self.assertNotEqual(legacy.returncode, 0)
            self.assertIn("no completion manifest", legacy.stdout)
            self.assertFalse((root / "commands.jsonl").exists())
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
            (backup / "unlisted.dump").write_text("must never be restored")
            result = ansible(
                "playbook",
                "-i",
                str(inventory),
                str(playbook),
                "-e",
                json.dumps(
                    variables
                    | {"restore_from": timestamp, "restore_services": "postgres"}
                ),
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                json.loads((root / "state.json").read_text())["replicas"],
                {"off-key_postgres": 1, "off-key_api": 1, "radar-runtime": 2},
            )
            # The node keeps no copy of the restored dumps.
            self.assertEqual(
                list((root / "live-stack/.backup").glob("*/**/*.dump")), []
            )
            commands = [
                json.loads(line)
                for line in (root / "commands.jsonl").read_text().splitlines()
            ]
            self.assertFalse(any("unlisted" in command for command in commands))
            # Every session the backup carried ends once the data is back.
            restored = next(
                index
                for index, command in enumerate(commands)
                if "pg_restore" in command
            )
            revoked = [
                index
                for index, command in enumerate(commands)
                if any("session_version + 1" in part for part in command)
            ]
            self.assertEqual(len(revoked), 1)
            self.assertGreater(revoked[0], restored)
            self.assertIn("fixture_db", commands[revoked[0]])

    def test_interrupted_fetch_never_publishes_a_complete_backup_or_replaces_tasks(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timestamp = "20260807T120000Z"
            backup = root / "backups/postgres" / timestamp
            (backup / "second_db.dump").mkdir(parents=True)
            result, state, commands = self.run_cutover(
                directory,
                extra_vars={"persistence_run_ts": timestamp},
                DATABASES="first_db\nsecond_db",
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((backup / "roles.sql").exists())
            self.assertTrue((backup / "first_db.dump").exists())
            self.assertFalse((backup / "manifest.json").exists())
            self.assertFalse(
                any(command[:2] == ["stack", "deploy"] for command in commands)
            )
            self.assertEqual(
                state["replicas"],
                {"off-key_postgres": 1, "off-key_api": 1, "radar-runtime": 2},
            )
            self.assertFalse((root / "stack/recovery-pending.json").exists())
            verified = run(
                sys.executable,
                str(ROOT / "scripts/backup_manifest.py"),
                "verify",
                str(backup),
                "postgres",
                timestamp,
                check=False,
            )
            self.assertNotEqual(verified.returncode, 0)
            self.assertIn("no completion manifest", verified.stderr)

    def test_damaged_backup_is_rejected_before_stopping_writers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timestamp = "20260807T120000Z"
            backup = root / "backups/postgres" / timestamp
            backup.mkdir(parents=True)
            (backup / "roles.sql").write_text("synthetic roles")
            (backup / "first_db.dump").write_text("synthetic data")
            run(
                sys.executable,
                str(ROOT / "scripts/backup_manifest.py"),
                "create",
                str(backup),
                "postgres",
                timestamp,
                "roles.sql",
                "first_db.dump",
            )
            (backup / "first_db.dump").write_text("damaged")
            playbook = root / "restore.yml"
            playbook.write_text(
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
            result = ansible(
                "playbook",
                "-i",
                "localhost,",
                str(playbook),
                "-e",
                json.dumps(
                    {
                        "ansible_connection": "local",
                        "ansible_become": False,
                        "ansible_python_interpreter": sys.executable,
                        "persistence_switch_confirm": True,
                        "stack_dir": str(root / "stack"),
                        "persistence_backup_dir": str(root / "backups"),
                        "restore_from": timestamp,
                        "restore_services": "postgres",
                    }
                ),
                check=False,
            )
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("checksum mismatch", result.stdout)
            self.assertFalse((root / "commands.jsonl").exists())
            self.assertFalse((root / "stack/recovery-pending.json").exists())

    def test_failed_backup_resumption_keeps_original_plan_and_reports_partial_resume(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timestamp = "20260807T120000Z"
            backup = root / "backups/postgres" / timestamp
            (backup / "second_db.dump").mkdir(parents=True)
            result, state, commands = self.run_cutover(
                directory,
                extra_vars={"persistence_run_ts": timestamp},
                DATABASES="first_db\nsecond_db",
                SCALE_FAIL_SERVICE="radar-runtime",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Some writers may already be running", result.stdout)
            plan = json.loads((root / "stack/recovery-pending.json").read_text())
            self.assertEqual(plan["phase"], "backup")
            self.assertEqual(plan["timestamp"], timestamp)
            self.assertEqual(
                plan["writer_replicas"], {"off-key_api": 1, "radar-runtime": 2}
            )
            self.assertEqual(
                state["replicas"],
                {"off-key_postgres": 1, "off-key_api": 1, "radar-runtime": 0},
            )
            self.assertFalse(
                any(command[:2] == ["stack", "deploy"] for command in commands)
            )

    def test_interrupted_multi_service_cutover_requires_whole_original_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "stack").mkdir()
            (root / "docker").write_text(f"#!{sys.executable}\n" + EMQX_DOCKER)
            (root / "docker").chmod(0o755)
            initial = {
                "replicas": {
                    "off-key_postgres": 1,
                    "off-key_emqx-main": 1,
                    "off-key_api": 1,
                    "radar-runtime": 2,
                },
                "deployed": False,
            }
            (root / "state.json").write_text(json.dumps(initial))
            inventory = root / "inventory.yml"
            inventory.write_text(
                yaml.safe_dump(
                    {
                        "all": {
                            "children": {
                                "swarm_manager": {
                                    "hosts": {
                                        "localhost": {"ansible_connection": "local"}
                                    }
                                }
                            }
                        }
                    }
                )
            )
            variables = {
                "ansible_become": False,
                "ansible_python_interpreter": sys.executable,
                "persistence_switch_confirm": True,
                "stack_name": "off-key",
                "postgres_user": "fixture",
                "stack_dir": str(root / "stack"),
                "persist_postgres": True,
                "persist_emqx_data": True,
                "persistence_backup_dir": str(root / "backups"),
            }
            env = os.environ | {
                "PATH": str(root) + os.pathsep + os.environ["PATH"],
                "DOCKER_FIXTURE": str(root),
                "EXPORT_MODE": "fresh",
                "ANSIBLE_CONFIG": str(ROOT / "ansible/ansible.cfg"),
            }
            cutover = root / "cutover.yml"
            cutover.write_text(
                yaml.safe_dump(
                    [
                        {
                            "hosts": "swarm_manager",
                            "gather_facts": False,
                            "tasks": [
                                {"include_role": {"name": "persistence_switch"}},
                                {
                                    "fail": {
                                        "msg": "Injected interruption before restore"
                                    }
                                },
                            ],
                        }
                    ]
                )
            )
            interrupted = ansible(
                "playbook",
                "-i",
                str(inventory),
                str(cutover),
                "-e",
                json.dumps(variables),
                env=env,
                check=False,
            )
            self.assertNotEqual(interrupted.returncode, 0)
            pending = root / "stack/recovery-pending.json"
            original_plan = pending.read_text()
            plan = json.loads(original_plan)
            self.assertEqual(plan["services"], ["emqx", "postgres"])
            self.assertEqual(sorted(plan["backup_paths"]), ["emqx", "postgres"])
            self.assertEqual(plan["phase"], "restore")
            mounts = {
                "off-key_postgres": [
                    {
                        "Type": "volume",
                        "Source": "off-key_postgres_data",
                        "Target": "/var/lib/postgresql/data",
                    }
                ],
                "off-key_emqx-main": [
                    {
                        "Type": "volume",
                        "Source": "off-key_emqx_data",
                        "Target": "/opt/emqx/data",
                    }
                ],
            }
            replacement = initial | {
                "deployed": True,
                "mounts": mounts,
                "replicas": initial["replicas"]
                | {"off-key_api": 0, "radar-runtime": 0},
            }
            (root / "state.json").write_text(json.dumps(replacement))
            restore = root / "restore.yml"
            restore.write_text((ROOT / "ansible/restore-stack-state.yml").read_text())
            (root / "validate-inventory.yml").write_text(
                (ROOT / "ansible/validate-inventory.yml").read_text()
            )
            restore_env = env | {
                "CONTAINER_MOUNTS": json.dumps(
                    [
                        {
                            "Type": "volume",
                            "Name": mount["Source"],
                            "Destination": mount["Target"],
                        }
                        for service_mounts in mounts.values()
                        for mount in service_mounts
                    ]
                )
            }

            def retry(
                timestamp=plan["timestamp"], services="postgres,emqx", **environment
            ):
                return ansible(
                    "playbook",
                    "-i",
                    str(inventory),
                    str(restore),
                    "-e",
                    json.dumps(
                        variables
                        | {"restore_from": timestamp, "restore_services": services}
                    ),
                    env=restore_env | environment,
                    check=False,
                )

            for timestamp, services in (
                (plan["timestamp"], "postgres"),
                ("20260807T120000Z", "postgres,emqx"),
            ):
                before = (root / "commands.jsonl").read_text()
                rejected = retry(timestamp, services)
                self.assertNotEqual(
                    rejected.returncode, 0, rejected.stdout + rejected.stderr
                )
                self.assertIn("entire service set", rejected.stdout)
                self.assertEqual(pending.read_text(), original_plan)
                self.assertEqual((root / "commands.jsonl").read_text(), before)
            replacement["replicas"].update({"off-key_api": 1, "radar-new": 1})
            (root / "state.json").write_text(json.dumps(replacement))
            commands = root / "commands.jsonl"
            before = len(commands.read_text().splitlines())
            unexpected = retry()
            self.assertNotEqual(unexpected.returncode, 0)
            self.assertIn("Stop these unexpected runtime writers", unexpected.stdout)
            self.assertEqual(pending.read_text(), original_plan)
            attempted = [
                json.loads(line) for line in commands.read_text().splitlines()[before:]
            ]
            self.assertFalse(
                any(
                    command[:2] == ["service", "scale"] or "pg_restore" in command
                    for command in attempted
                )
            )
            self.assertEqual(
                json.loads((root / "state.json").read_text())["replicas"][
                    "off-key_api"
                ],
                1,
            )
            replacement["replicas"]["radar-new"] = 0
            (root / "state.json").write_text(json.dumps(replacement))
            failed = retry(RESTORE_FAIL="1")
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual(pending.read_text(), original_plan)
            self.assertEqual(
                json.loads((root / "state.json").read_text())["replicas"][
                    "off-key_api"
                ],
                0,
            )
            completed = retry()
            self.assertEqual(
                completed.returncode, 0, completed.stdout + completed.stderr
            )
            final = json.loads((root / "state.json").read_text())
            self.assertTrue(final["emqx_restored"])
            self.assertEqual(final["replicas"], initial["replicas"] | {"radar-new": 0})
            self.assertFalse(pending.exists())

    def test_log_only_cutover_preserves_ephemeral_emqx_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = EMQX_DOCKER.replace(
                "off-key_postgres\\noff-key_api", "off-key_emqx-main\\noff-key_api"
            ).replace("name == 'off-key_postgres'", "name == 'off-key_emqx-main'")
            fixture = fixture.replace(
                "/var/lib/postgresql/data", "/opt/emqx/log"
            ).replace("off-key_postgres_data", "off-key_emqx_log")
            (root / "docker").write_text(f"#!{sys.executable}\n" + fixture)
            (root / "docker").chmod(0o755)
            initial = {
                "replicas": {
                    "off-key_emqx-main": 1,
                    "off-key_api": 1,
                    "radar-runtime": 2,
                },
                "deployed": False,
            }
            (root / "state.json").write_text(json.dumps(initial))
            replacement = {
                "replicas": {
                    "off-key_emqx-main": 1,
                    "off-key_api": 0,
                    "radar-runtime": 0,
                },
                "deployed": True,
            }
            playbook = root / "cutover.yml"
            playbook.write_text(
                yaml.safe_dump(
                    [
                        {
                            "hosts": "localhost",
                            "gather_facts": False,
                            "tasks": [
                                {"include_role": {"name": "persistence_switch"}},
                                {
                                    "copy": {
                                        "dest": str(root / "state.json"),
                                        "content": json.dumps(replacement),
                                    }
                                },
                                {
                                    "include_role": {
                                        "name": "persistence_switch",
                                        "tasks_from": "restore",
                                    }
                                },
                            ],
                        }
                    ]
                )
            )
            variables = {
                "ansible_connection": "local",
                "ansible_become": False,
                "ansible_python_interpreter": sys.executable,
                "persistence_switch_confirm": True,
                "stack_name": "off-key",
                "stack_dir": str(root / "stack"),
                "persist_emqx_log": True,
                "persistence_backup_dir": str(root / "backups"),
            }
            env = os.environ | {
                "PATH": str(root) + os.pathsep + os.environ["PATH"],
                "DOCKER_FIXTURE": str(root),
                "EXPORT_MODE": "fresh",
                "ANSIBLE_CONFIG": str(ROOT / "ansible/ansible.cfg"),
            }
            result = ansible(
                "playbook",
                "-i",
                "localhost,",
                str(playbook),
                "-e",
                json.dumps(variables),
                env=env,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(
                json.loads((root / "state.json").read_text())["emqx_restored"]
            )
            self.assertEqual(
                len(list((root / "backups/emqx").glob("*/emqx-export-fresh.tar.gz"))), 1
            )
