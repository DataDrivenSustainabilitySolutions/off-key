"""Exercise recovery orchestration against a local, stateful Docker CLI fixture."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from support import ROOT, ansible, run

DOCKER = r"""
import json, os, sys
from pathlib import Path
root = Path(os.environ['DOCKER_FIXTURE'])
state_file = root / 'state.json'
state = json.loads(state_file.read_text())
a = sys.argv[1:]
with (root / 'commands.jsonl').open('a') as log:
    log.write(json.dumps(a) + '\n')

def spec(name):
    result = {'Spec': {'Name': name, 'Mode': {'Replicated': {'Replicas': state['replicas'][name]}},
            'TaskTemplate': {'ContainerSpec': {'Image': 'example/' + name,
              'Mounts': [{'Type': 'volume', 'Source': 'off-key_postgres_data',
                          'Target': '/var/lib/postgresql/data'}]
                        if name == 'off-key_postgres' and (state.get('persistent', state['deployed'])
                            or (state['deployed'] and os.environ.get('CONFIGURED_MOUNT'))) else []}}}}
    if name in state.get('mounts', {}):
        result['Spec']['TaskTemplate']['ContainerSpec']['Mounts'] = state['mounts'][name]
    return result

if a[:2] == ['compose', '--env-file']:
    if a[-2:] == ['--format', 'json']:
        print(json.dumps({'services': {'postgres': {'image': 'example/postgres', 'deploy': {'replicas': 1}},
                                      'api': {'image': 'example/api', 'deploy': {'replicas': 1}}}}))
    else:
        assert '-f' in a and any('persistence-cutover.yml' in v for v in a)
        print('services: {}')
elif a[:2] == ['service', 'inspect']:
    names = a[2:]
    if any(name not in state['replicas'] for name in names):
        sys.exit(1)
    print(json.dumps([spec(name) for name in names]))
elif a[:2] == ['service', 'ls']:
    if 'label=managed_by=tactic' in a:
        print('\n'.join(name for name in state['replicas'] if name.startswith('radar-')))
    elif '--quiet' in a:
        print('off-key_postgres\noff-key_api')
    else:
        print('fixture services')
elif a[:2] == ['service', 'scale']:
    name, replicas = a[2].split('=')
    if int(replicas) and name == os.environ.get('SCALE_FAIL_SERVICE'):
        sys.exit(1)
    state['replicas'][name] = int(replicas)
elif a[:2] == ['service', 'ps']:
    name = next(v for v in a[2:] if v in state['replicas'])
    if '--quiet' in a:
        print(name + '-task')
    elif state['replicas'][name]:
        print(json.dumps({'ID': name + ('-new' if state['deployed'] else '-old'),
                          'Node': 'localhost', 'CurrentState': 'Running 1 minute ago'}))
elif a[:3] == ['inspect', '--type', 'task']:
    name = a[-1].removesuffix('-task')
    print('running' if state['replicas'][name] else 'shutdown')
elif a[:2] == ['volume', 'inspect']:
    sys.exit(1)
elif a[0] == 'ps':
    task_filter = next((v for v in a if v.startswith('label=com.docker.swarm.task.id=')), None)
    if task_filter:
        print('replacement' if task_filter.endswith('-new') else 'original')
    else:
        print('retiring-old-container\nreplacement')
elif a[0] == 'inspect':
    assert a[1] == 'replacement'
    mounts = [{'Destination': '/var/lib/postgresql/data', 'Type': 'volume',
               'Name': 'wrong-volume' if os.environ.get('WRONG_MOUNT') else
                       ('off-key_postgres_data' if state.get('persistent', True) else 'anonymous-volume')}]
    print(json.dumps({'mounts': json.loads(os.environ.get('CONTAINER_MOUNTS', json.dumps(mounts))),
                      'image_volumes': json.loads(os.environ.get('IMAGE_VOLUMES', '{"/var/lib/postgresql/data":{}}'))}))
elif a[:2] == ['stack', 'deploy']:
    model = json.loads(Path(a[a.index('-c') + 1]).read_text())
    assert model['services']['api']['deploy']['replicas'] == 0
    assert state['replicas']['off-key_api'] == state['replicas']['radar-runtime'] == 0
    assert state['replicas']['off-key_postgres'] == 0
    state['deployed'] = True
    state['persistent'] = os.environ.get('PERSIST_POSTGRES', '1') == '1'
    state['replicas']['off-key_postgres'] = 1
elif a[0] == 'exec':
    cid = a[2] if a[1] == '-i' else a[1]
    if 'pg_dumpall' in a or 'pg_dump' in a:
        assert cid == 'original' and state['replicas']['off-key_api'] == 0
        print('-- fixture backup')
    elif 'pg_restore' in a:
        assert cid == ('original' if os.environ.get('MANUAL_RESTORE') else 'replacement') and state['replicas']['off-key_api'] == 0
        assert state['replicas']['radar-runtime'] == 0
        if os.environ.get('RESTORE_FAIL'):
            sys.exit(1)
    elif 'psql' in a:
        if '-At' in a:
            print(os.environ.get('DATABASES', 'fixture_db'))
        elif '-tc' in a:
            print('1')
    elif not any(command in a for command in ('pg_isready', 'dropdb', 'createdb')):
        sys.exit('unexpected exec: ' + repr(a))
else:
    sys.exit('unexpected command: ' + repr(a))
state_file.write_text(json.dumps(state))
"""


EMQX_DOCKER = DOCKER.replace(
    "elif a[0] == 'exec':",
    """elif a[0] == 'exec' and 'emqx' in a:
    if a[-2:] == ['ctl', 'status']:
        if os.environ['EXPORT_MODE'] == 'unready':
            sys.exit(1)
        print('Node emqx@emqx-main.internal is started')
    elif a[-3:] == ['ctl', 'data', 'export']:
        state['exported'] = True
    elif a[-4:-1] == ['ctl', 'data', 'import']:
        assert state['replicas']['off-key_api'] == 0
        state['emqx_restored'] = True
    else:
        sys.exit(2)
elif a[0] == 'exec' and ('find' in a or 'sh' in a):
    print('/opt/emqx/data/backup/stale.tar.gz')
    if state.get('exported') and os.environ['EXPORT_MODE'] == 'fresh':
        print('/opt/emqx/data/backup/emqx-export-fresh.tar.gz')
elif a[0] == 'cp':
    assert Path(a[1]).exists()
elif a[0] == 'exec' and 'mkdir' in a:
    pass
elif a[0] == 'exec' and 'cat' in a:
    print('fixture archive')
elif a[0] == 'exec':""",
)


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
            "offkey_env": "dev",
            "stack_name": "off-key",
            "stack_dir": str(root / "stack"),
            "stack_compose_files": [str(root / "stack/compose.yml")],
            "postgres_user": "fixture",
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
                self.assertTrue(
                    list(
                        (Path(directory) / "backups/postgres").glob("*/fixture_db.dump")
                    )
                )
                self.assertFalse(
                    (Path(directory) / "stack/recovery-pending.json").exists()
                )

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
                    "offkey_env": "dev",
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
            backup = root / "stack/state/dev/postgres" / timestamp
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
                "offkey_env": "dev",
                "stack_name": "off-key",
                "postgres_user": "fixture",
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
            self.assertEqual(
                len(
                    list(
                        (root / "live-stack/.backup").glob("*/restore/fixture_db.dump")
                    )
                ),
                1,
            )
            commands = [
                json.loads(line)
                for line in (root / "commands.jsonl").read_text().splitlines()
            ]
            self.assertFalse(any("unlisted" in command for command in commands))

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
                        "offkey_env": "dev",
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
                "offkey_env": "dev",
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
                "offkey_env": "dev",
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
