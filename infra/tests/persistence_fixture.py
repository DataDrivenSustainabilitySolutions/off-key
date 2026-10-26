"""Stateful Docker CLI fixtures for persistence backup and recovery tests."""

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
    if name.startswith('radar-'):
        # TACTIC attaches its workers to its own stack's broker network.
        result['Spec']['TaskTemplate']['Networks'] = [{'Target': 'off-key_emqx-network'}]
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
    # Explicit actual task states can lag behind desired replica counts.
    sequence = state.get('task_state_sequences', {}).get(name)
    if sequence:
        print(sequence.pop(0) if len(sequence) > 1 else sequence[0])
    else:
        print('running' if state['replicas'][name] else 'shutdown')
elif a[:2] in (['volume', 'inspect'], ['network', 'inspect']):
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
