"""Run the real configuration tools against temporary, non-secret inputs."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd=ROOT, env=None, input=None, check=True, timeout=180):
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
        timeout=timeout,
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


CLIENTS = ("100.100.10.2", "100.100.10.3")
TOKEN = "eyJ" + "validation-only-not-a-real-token-" * 3


def discovery(addresses):
    return {
        "results": [
            {
                "item": f"backend-{i}",
                "stdout": address,
                "stdout_lines": address.splitlines(),
            }
            for i, address in enumerate(addresses)
        ]
    }


def render(directory, environment, **overrides):
    variables = {
        "validation_environment": environment,
        "internal_api_secret": "validation-internal-service-secret-123456789",
        "stack_dir": str(directory / "stack"),
        "stack_file_owner": str(os.getuid()),
        "stack_file_group": str(os.getgid()),
        "ansible_python_interpreter": sys.executable,
        "ambibox_nfs_addr": "100.100.10.1",
        "ambibox_nfs_backend_ips": discovery(CLIENTS),
        "cloudflare_tunnel_token": TOKEN,
        "tailscale_ambibox_extra_args": "--accept-dns --advertise-tags=tag:fixture --login-server=https://vpn.example.invalid",
        "tailscale_ambibox_hostname": "fixture-tailnet-host",
        "ambibox_access": {
            "mqtt_username": "fixture-vendor",
            "mqtt_password": "fixture-vendor-password",
            "api_key": "fixture-controller",
            "api_secret": "a" * 64,
            "gost_password": "g" * 64,
        },
    } | overrides
    if environment == "prod":
        variables = {
            "emqx_ca_cert": (
                "-----BEGIN CERTIFICATE-----\n"
                + "A" * 120
                + "\n-----END CERTIFICATE-----\n"
            ),
            "emqx_server_cert": (
                "-----BEGIN CERTIFICATE-----\n"
                + "B" * 120
                + "\n-----END CERTIFICATE-----\n"
            ),
            "emqx_server_key": (
                "-----BEGIN "
                + "PRIVATE KEY-----\n"
                + "C" * 120
                + "\n-----END PRIVATE KEY-----\n"
            ),
            "mqtt_proxy_password": "proxy-" + "p" * 32,
            "mqtt_radar_password": "radar-" + "r" * 32,
            "radar_checkpoint_secret": "checkpoint-" + "c" * 32,
            "email_password": "re_validation_only_not_a_real_key",
        } | variables
    inputs = directory / "inputs.json"
    inputs.write_text(json.dumps(variables))
    result = ansible(
        "playbook",
        "-i",
        "localhost,",
        str(ROOT / "tests/render-deployment.yml"),
        "--extra-vars",
        f"@{inputs}",
        check=False,
    )
    return result, variables
