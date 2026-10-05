"""Run the real configuration tools against temporary, non-secret inputs."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd=ROOT, env=None, input=None, check=True):
    process_env = os.environ.copy()
    process_env.update(
        ANSIBLE_CONFIG=str(ROOT / "ansible/ansible.cfg"),
        ANSIBLE_NOCOLOR="1",
        ANSIBLE_DUPLICATE_YAML_DICT_KEY="error",
    )
    if env is not None:
        process_env = env
    result = subprocess.run(
        args,
        cwd=cwd,
        env=process_env,
        input=input,
        text=True,
        check=False,
        capture_output=True,
        timeout=180,
    )
    if check and result.returncode:
        raise AssertionError(
            f"Command failed ({result.returncode}): {' '.join(map(str, args))}\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return result


def ansible(command, *args, **kwargs):
    return run(sys.executable, "-m", f"ansible.cli.{command}", *args, **kwargs)


def load_inventory(path):
    return json.loads(ansible("inventory", "-i", str(path), "--list").stdout)
