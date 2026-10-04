"""Exercise recovery orchestration against a local, stateful Docker CLI fixture."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from support import ROOT, ansible

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
    return {'Spec': {'Name': name, 'Mode': {'Replicated': {'Replicas': state['replicas'][name]}},
            'TaskTemplate': {'ContainerSpec': {'Image': 'example/' + name,
              'Mounts': [{'Target': '/var/lib/postgresql/data'}] if name == 'off-key_postgres' and state['deployed'] else []}}}}

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
        print('radar-runtime')
    elif '--quiet' in a:
        print('off-key_postgres\noff-key_api')
    else:
        print('fixture services')
elif a[:2] == ['service', 'scale']:
    name, replicas = a[2].split('=')
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
    print(json.dumps([{'Destination': '/var/lib/postgresql/data', 'Type': 'volume',
                      'Name': 'wrong-volume' if os.environ.get('WRONG_MOUNT') else 'off-key_postgres_data'}]))
elif a[:2] == ['stack', 'deploy']:
    model = json.loads(Path(a[a.index('-c') + 1]).read_text())
    assert model['services']['api']['deploy']['replicas'] == 0
    assert state['replicas']['off-key_api'] == state['replicas']['radar-runtime'] == 0
    assert state['replicas']['off-key_postgres'] == 0
    state['deployed'] = True
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
            print('fixture_db')
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
    def run_cutover(self, directory, **environment):
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
            "persist_postgres": True,
            "persistence_backup_dir": str(root / "backups"),
        }
        env = (
            os.environ
            | {
                "PATH": str(root) + os.pathsep + os.environ["PATH"],
                "DOCKER_FIXTURE": str(root),
                "ANSIBLE_CONFIG": str(ROOT / "ansible/ansible.cfg"),
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
        with tempfile.TemporaryDirectory() as directory:
            result, state, commands = self.run_cutover(directory)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                state["replicas"],
                {"off-key_postgres": 1, "off-key_api": 1, "radar-runtime": 2},
            )
            restore = next(command for command in commands if "pg_restore" in command)
            self.assertEqual(restore[1:3], ["-i", "replacement"])
            self.assertTrue(
                list((Path(directory) / "backups/postgres").glob("*/fixture_db.dump"))
            )
            self.assertFalse((Path(directory) / "stack/recovery-pending.json").exists())

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

    def test_log_only_cutover_preserves_ephemeral_emqx_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = EMQX_DOCKER.replace(
                "off-key_postgres\\noff-key_api", "off-key_emqx-main\\noff-key_api"
            )
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
