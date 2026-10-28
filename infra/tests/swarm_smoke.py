"""Run existing E2E tests against production images in an isolated local Swarm.

The production render, MQTT TLS/secrets, migration, persistence and verification
tasks are reused. External VPN/Cloudflare/email dependencies are local fixtures.
Main uses published immutable images; PRs build the same runtime targets locally.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml
from rehearsal_releases import (
    build_local_images,
    compatible_release,
    record_cutover,
    release_model,
    selected_release,
    stop_registry,
)
from support import ROOT, render, run

sys.path.insert(0, str(ROOT / "scripts"))
from compile_stack import compile_stack
from pin_release import APPLICATION_IMAGES, pin

PROJECT = ROOT.parent
STACK = "offkey-smoke"


def wait(probe, description, timeout=300):
    deadline = time.monotonic() + timeout
    failure = None
    while time.monotonic() < deadline:
        try:
            return probe()
        except (AssertionError, ValueError, subprocess.SubprocessError) as error:
            failure = error
            time.sleep(3)
    raise AssertionError(f"Timed out waiting for {description}: {failure}")


def container(service):
    result = run(
        "docker",
        "ps",
        "-q",
        "--filter",
        f"label=com.docker.swarm.service.name={STACK}_{service}",
        "--filter",
        "status=running",
    ).stdout.splitlines()
    if len(result) != 1:
        raise ValueError(f"Expected one running {service} container")
    return result[0]


def ready(directory):
    wait(
        lambda: run(
            sys.executable,
            ROOT / "scripts/check_swarm.py",
            STACK,
            directory / "stack/deployment-model.json",
            json.loads((directory / "inputs.json").read_text())["release"]["images"][
                "mqtt_radar"
            ],
        ),
        "Swarm convergence",
    )
    wait(
        lambda: run(
            "docker",
            "exec",
            "-i",
            container("mqtt-proxy"),
            "/app/bin/python",
            "-",
            input=(ROOT / "scripts/check_application.py").read_text(),
        ),
        "application readiness",
    )


def deploy(directory, phase, **overrides):
    values = (
        json.loads((directory / "inputs.json").read_text())
        | overrides
        | {
            "rehearsal_phase": phase,
            "ansible_become": False,
            "release_public_urls": ["http://localhost:5173"],
            "persistence_backup_dir": str(directory / "backups"),
        }
    )
    variables = directory / "deployment-inputs.json"
    variables.write_text(json.dumps(values))
    run(
        "uv",
        "run",
        "--frozen",
        "--project",
        ROOT,
        "ansible-playbook",
        "-i",
        directory / "inventory.yml",
        ROOT / "tests/rehearse-deployment.yml",
        "-e",
        f"@{variables}",
        timeout=900,
    )


def images(release, revision):
    if (
        os.getenv("GITHUB_EVENT_NAME") == "push"
        and os.getenv("GITHUB_REF") == "refs/heads/main"
    ):
        # This run's publish job pushed these images before the lane started.
        # Allow brief registry propagation, then verify each digest's revision.
        for name in sorted(APPLICATION_IMAGES):
            release["images"][name] = wait(
                lambda name=name: pin(release["images"][name], revision),
                f"published {name} image",
                timeout=60,
            )
        return

    build_local_images(release, revision, PROJECT)


def prepare(directory):
    if run("docker", "service", "ls", "-q").stdout.strip():
        raise ValueError("The rehearsal requires a Swarm with no existing services")
    node = run(
        "docker", "node", "inspect", "self", "--format", "{{.Description.Hostname}}"
    ).stdout.strip()
    node_spec = json.loads(run("docker", "node", "inspect", "self").stdout)[0]
    (directory / "node.json").write_text(json.dumps(node_spec))
    run(
        "docker",
        "node",
        "update",
        "--label-add",
        "backend=true",
        "--label-add",
        "frontend=true",
        node_spec["ID"],
    )
    (directory / "inventory.yml").write_text(
        json.dumps(
            {
                "all": {
                    "hosts": {node: {"ansible_connection": "local"}},
                    "children": {"swarm_manager": {"hosts": {node: {}}}},
                }
            }
        )
    )
    release = json.loads(
        (ROOT / "ansible/inventories/prod/group_vars/all/release.yml").read_text()
    )["release"]
    socket_proxy = os.getenv("OFFKEY_REHEARSAL_SOCKET_PROXY_IMAGE")
    if socket_proxy:
        if os.getenv("CI"):
            raise ValueError(
                "CI must rehearse the canonical production platform images"
            )
        # The production proxy is amd64-only. Local ARM rehearsals can supply a
        # compatible native proxy; release CI always checks the canonical image.
        release["images"]["socket_proxy"] = pin(socket_proxy)
    revision = (
        os.getenv("GITHUB_SHA")
        or run("git", "rev-parse", "HEAD", cwd=PROJECT).stdout.strip()
    )
    images(release, revision)
    release["application_revision"] = revision
    (directory / "production-release.json").write_text(
        json.dumps({"release": release}, indent=2)
    )

    run(
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "2",
        "-subj",
        "/CN=offkey-smoke-ca",
        "-addext",
        "basicConstraints=critical,CA:TRUE",
        "-addext",
        "keyUsage=critical,keyCertSign,cRLSign",
        "-keyout",
        directory / "ca.key",
        "-out",
        directory / "ca.crt",
    )
    run(
        "openssl",
        "req",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-subj",
        "/CN=emqx-main",
        "-keyout",
        directory / "broker.key",
        "-out",
        directory / "broker.csr",
    )
    (directory / "certificate.ext").write_text(
        "basicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\n"
        "subjectAltName=DNS:emqx-main,DNS:localhost,IP:127.0.0.1\n"
    )
    run(
        "openssl",
        "x509",
        "-req",
        "-days",
        "2",
        "-in",
        directory / "broker.csr",
        "-CA",
        directory / "ca.crt",
        "-CAkey",
        directory / "ca.key",
        "-CAcreateserial",
        "-extfile",
        directory / "certificate.ext",
        "-out",
        directory / "broker.crt",
    )
    result, inputs = render(
        directory,
        "prod",
        release=release,
        stack_name=STACK,
        jwt_secret="synthetic-smoke-signing-secret-123456789",
        postgres_password="synthetic-smoke-database-password",
        emqx_dashboard_password="synthetic-smoke-dashboard-password",
        emqx_ca_cert=(directory / "ca.crt").read_text(),
        emqx_server_cert=(directory / "broker.crt").read_text(),
        emqx_server_key=(directory / "broker.key").read_text(),
        frontend_base_url="http://localhost:5173",
        cors_allowed_origins='["http://localhost:5173"]',
        smtp_server="smtp-fixture",
        smtp_port="1025",
        mail_starttls="False",
        mail_ssl_tls="False",
        use_credentials="False",
        validate_certs="False",
        email_from="offkey@example.com",
        superuser_mail="admin@example.com",
        anomaly_alert_recipients="admin@example.com",
        access_token_expire_minutes="120",
        log_level="INFO",
        tactic_log_level="INFO",
        # Cutovers must recover existing graph runs with authoring disabled.
        # The workflow enables authoring separately for creation/browser tests.
        tactic_pipeline_authoring_enabled=False,
        tactic_docker_default_network=f"{STACK}_emqx-network",
        tactic_docker_additional_networks=f"{STACK}_app-network",
        # The production route secret, covering only the test broker.
        broker_route_hosts=["source-broker"],
        broker_route_host_suffixes=[],
    )
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    files = json.loads((directory / "stack/validation.json").read_text())[
        "compose_files"
    ]
    args = [
        "docker",
        "compose",
        "--project-name",
        STACK,
        "--env-file",
        directory / "stack/.env",
    ]
    for file in files:
        args += ["-f", file]
    model = compile_stack(json.loads(run(*args, "config", "--format", "json").stdout))
    # Replace only external dependencies. Keep canonical application settings,
    # commands, placement, volumes, TLS and secret wiring from the production model.
    for name in ("cloudflared", "traefik", "oauth2-proxy", "landing"):
        model["services"].pop(name, None)
    # A plain SOCKS proxy stands in for the route's Tailscale node.
    model["services"]["broker-route"] = {
        "image": release["images"]["gost"],
        "command": ["-L", "socks5://:1055"],
        "networks": ["app-network", "emqx-network"],
        "deploy": {"replicas": 1},
    }
    model["services"]["source-broker"] = {
        "image": pin("eclipse-mosquitto:2.0"),
        "networks": ["emqx-network"],
        "configs": [
            {
                "source": "source-broker-config",
                "target": "/mosquitto/config/mosquitto.conf",
            }
        ],
        "ports": [{"target": 1883, "published": 1884, "mode": "host"}],
    }
    model["configs"]["source-broker-config"] = {
        "file": str(PROJECT / "dev/mosquitto/mosquitto.conf")
    }
    model["services"]["smtp-fixture"] = {
        "image": pin("axllent/mailpit:latest"),
        "networks": ["app-network"],
    }
    for service, port, published in (
        ("frontend", 5173, 5173),
        ("api", 8000, int(os.getenv("OFFKEY_REHEARSAL_API_PORT", "8000"))),
        ("tactic", 8001, 8001),
        ("emqx-main", 8883, 8883),
        ("smtp-fixture", 8025, 8025),
    ):
        model["services"][service]["ports"] = [
            {"target": port, "published": published, "mode": "host"}
        ]
    used_configs = {
        item["source"]
        for service in model["services"].values()
        for item in service.get("configs", [])
    }
    model["configs"] = {
        name: value
        for name, value in model.get("configs", {}).items()
        if name in used_configs
    }
    model["volumes"].pop("broker-route-state", None)
    secret_values = json.loads((directory / "stack/validation.json").read_text())[
        "deployment_secret_material"
    ]
    used_secrets = {
        item["source"]
        for service in model["services"].values()
        for item in service.get("secrets", [])
    }
    model["secrets"] = {
        name: value for name, value in model["secrets"].items() if name in used_secrets
    }
    (directory / "stack/deployment-model.json").write_text(json.dumps(model))
    (directory / "stack/base-deployment-model.json").write_text(json.dumps(model))
    created_secrets = []
    for name, definition in model["secrets"].items():
        run(
            "docker",
            "secret",
            "create",
            definition["name"],
            "-",
            input=secret_values[name],
        )
        created_secrets.append(definition["name"])
        (directory / "created-secrets.json").write_text(json.dumps(created_secrets))
    # Production seeds this private image on backend nodes before runtime monitors
    # start. The single rehearsal node already has the temporary registry login.
    run("docker", "pull", release["images"]["mqtt_radar"], timeout=300)
    # Services an earlier layout ran that this release's successors replace,
    # such as a node identity that must never run twice. They must be gone
    # before the release starts its own.
    replaced = yaml.safe_load(
        (ROOT / "ansible/inventories/prod/group_vars/all/vars.yml").read_text()
    ).get("stack_replaced_services", [])
    for name in replaced:
        run(
            "docker",
            "service",
            "create",
            "--quiet",
            "--name",
            f"{STACK}_{name}",
            "--label",
            f"com.docker.stack.namespace={STACK}",
            "--constraint",
            "node.labels.backend==true",
            release["images"]["gost"],
            "-L",
            "socks5://:1055",
            timeout=180,
        )
    deploy(directory, "apply", release_bootstrap=True)
    services = run(
        "docker", "service", "ls", "--format", "{{.Name}}"
    ).stdout.splitlines()
    for name in replaced:
        if f"{STACK}_{name}" in services:
            raise AssertionError(f"The release kept the replaced service {name}")
    ready(directory)
    invitation = run(
        "docker",
        "exec",
        container("tactic"),
        "/app/bin/python",
        "-m",
        "off_key_tactic_middleware.bootstrap_admin",
    ).stdout.splitlines()[-1]
    print(f"::add-mask::{invitation}", flush=True)
    (directory / "smoke.env").write_text(
        f"E2E_BOOTSTRAP_URL={invitation}\nSUPERUSER_MAIL=admin@example.com\n"
        "MQTT_SOURCE_URL=mqtt://localhost:1884\nMQTT_INGRESS_URL=mqtts://localhost:8883\n"
        "MAILPIT_BASE_URL=http://127.0.0.1:8025\n"
        "E2E_MQTT_CA_FILE=/smoke/ca.crt\nE2E_MQTT_USERNAME=offkey-radar\n"
        f"E2E_MQTT_PASSWORD={inputs['mqtt_radar_password']}\nPLAYWRIGHT_BASE_URL=http://localhost:5173\n"
    )
    deploy(directory, "verify")
    print("Production Swarm is ready for the existing E2E suite", flush=True)


def redeploy(directory, restore, target="current"):
    model_path = directory / "stack/deployment-model.json"
    release = selected_release(directory, target)
    inputs_path = directory / "inputs.json"
    inputs = json.loads(inputs_path.read_text())
    inputs["release"] = release
    inputs_path.write_text(json.dumps(inputs))
    model = release_model(
        json.loads((directory / "stack/base-deployment-model.json").read_text()),
        release,
    )
    if restore:
        model["services"]["postgres"].pop("volumes", None)
    model_path.write_text(json.dumps(model))
    deploy(
        directory,
        "apply",
        persist_postgres=not restore,
        persistence_switch_confirm=True,
    )
    ready(directory)
    deploy(directory, "verify", persist_postgres=not restore)
    record_cutover(directory, release, target, restore, STACK)
    print(
        f"Production deployment and verification completed: {release['application_revision']}",
        flush=True,
    )


def cleanup(directory):
    if not (directory / "node.json").exists():
        return
    # Runtime workers are separate services, but attach to this stack's networks.
    networks = set(
        run(
            "docker",
            "network",
            "ls",
            "-q",
            "--no-trunc",
            "--filter",
            f"label=com.docker.stack.namespace={STACK}",
        ).stdout.splitlines()
    )
    for line in run(
        "docker",
        "service",
        "ls",
        "--format",
        "{{.ID}} {{.Name}}",
        "--filter",
        "label=managed_by=tactic",
    ).stdout.splitlines():
        identifier, name = line.split()
        service = json.loads(run("docker", "service", "inspect", identifier).stdout)[0]
        if networks.intersection(
            item["Target"]
            for item in service["Spec"]["TaskTemplate"].get("Networks", [])
        ):
            run("docker", "service", "rm", identifier, check=False)
    volumes = run(
        "docker",
        "volume",
        "ls",
        "-q",
        "--filter",
        f"label=com.docker.stack.namespace={STACK}",
    ).stdout.splitlines()
    run("docker", "stack", "rm", STACK, check=False)
    for volume in volumes:
        wait(
            lambda volume=volume: run("docker", "volume", "rm", "-f", volume),
            "rehearsal volume removal",
            timeout=90,
        )
    stop_registry()
    node = json.loads((directory / "node.json").read_text())
    for label in ("backend", "frontend"):
        if label in node["Spec"].get("Labels", {}):
            run(
                "docker",
                "node",
                "update",
                "--label-add",
                f"{label}={node['Spec']['Labels'][label]}",
                node["ID"],
            )
        else:
            run("docker", "node", "update", "--label-rm", label, node["ID"])
    if (directory / "created-secrets.json").exists():
        for name in json.loads((directory / "created-secrets.json").read_text()):
            wait(
                lambda name=name: run("docker", "secret", "rm", name),
                "rehearsal secret removal",
                timeout=90,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=("prepare", "prepare-rollback", "redeploy", "cleanup")
    )
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--restore", action="store_true")
    parser.add_argument("--reference-repository", type=Path)
    parser.add_argument(
        "--release", choices=("current", "compatible"), default="current"
    )
    args = parser.parse_args()
    args.directory = args.directory.resolve()
    args.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.action == "prepare":
        prepare(args.directory)
    elif args.action == "prepare-rollback":
        compatible_release(args.directory, PROJECT, args.reference_repository)
    elif args.action == "redeploy":
        redeploy(args.directory, args.restore, args.release)
    else:
        cleanup(args.directory)
