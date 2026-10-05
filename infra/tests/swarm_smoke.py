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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from support import ROOT, render, run

sys.path.insert(0, str(ROOT / "scripts"))
from compile_stack import compile_stack
from pin_release import APPLICATION_IMAGES, pin

PROJECT = ROOT.parent
STACK = "offkey-smoke"
REGISTRY = "offkey-smoke-registry"
BUILDS = {
    "api": ("off-key-api-gateway", "services/api/gateway"),
    "tactic": ("off-key-tactic-middleware", "services/middleware/tactic"),
    "mqtt_proxy": ("off-key-mqtt-proxy", "services/mqtt/proxy"),
    "mqtt_radar": ("off-key-mqtt-radar", "services/mqtt/radar"),
    "db_sync": ("off-key-db-sync", "services/db/sync"),
    "frontend": ("off-key-frontend", None),
}


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
        # Docker Publish runs concurrently. A digest and its full revision label
        # must exist before this job tests it. No mutable tag reaches deployment.
        for name in sorted(APPLICATION_IMAGES):
            release["images"][name] = wait(
                lambda name=name: pin(release["images"][name], revision),
                f"published {name} image",
                timeout=1200,
            )
        return

    run(
        "docker",
        "run",
        "-d",
        "--name",
        REGISTRY,
        "-p",
        "127.0.0.1:5010:5000",
        "registry:3",
    )

    def build(item):
        name, (service, source) = item
        reference = f"localhost:5010/{service}:smoke"
        args = [
            "docker",
            "build",
            "--label",
            f"org.opencontainers.image.revision={revision}",
            "-t",
            reference,
        ]
        if source is None:
            args += ["--target", "production", str(PROJECT / "frontend")]
        else:
            args += [
                "--build-arg",
                f"SERVICE_NAME={service}",
                "--build-arg",
                f"SERVICE_ROOT={source}",
                str(PROJECT / "backend"),
            ]
        print(f"Building production {name}", flush=True)
        run(*args, timeout=900)
        run("docker", "push", reference, timeout=300)
        references = json.loads(
            run(
                "docker",
                "image",
                "inspect",
                reference,
                "--format",
                "{{json .RepoDigests}}",
            ).stdout
        )
        return name, next(
            value
            for value in references
            if value.startswith(reference.split(":smoke")[0] + "@")
        )

    with ThreadPoolExecutor(max_workers=3) as pool:
        release["images"].update(pool.map(build, BUILDS.items()))


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
        tactic_docker_default_network=f"{STACK}_emqx-network",
        tactic_docker_additional_networks=f"{STACK}_app-network",
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
    model["services"]["tailscale-ambibox"] = {
        "image": release["images"]["gost"],
        "command": ["-L", "socks5://:1055"],
        "networks": ["emqx-network"],
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
    for service, port in (
        ("frontend", 5173),
        ("api", 8000),
        ("tactic", 8001),
        ("emqx-main", 8883),
    ):
        model["services"][service]["ports"] = [
            {"target": port, "published": port, "mode": "host"}
        ]
    # The controller's production allowlist is private. Only the test broker is dialled.
    model["services"]["tactic"]["environment"].update(
        AMBIBOX_ALLOWED_HOSTS='["source-broker"]'
    )
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
    model["volumes"].pop("tailscale-ambibox-state", None)
    secret_values = json.loads((directory / "stack/validation.json").read_text())[
        "mqtt_secret_material"
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
    deploy(directory, "apply", release_bootstrap=True)
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
        "E2E_MQTT_CA_FILE=/smoke/ca.crt\nE2E_MQTT_USERNAME=offkey-radar\n"
        f"E2E_MQTT_PASSWORD={inputs['mqtt_radar_password']}\nPLAYWRIGHT_BASE_URL=http://localhost:5173\n"
    )
    deploy(directory, "verify")
    print("Production Swarm is ready for the existing E2E suite", flush=True)


def redeploy(directory, restore):
    model_path = directory / "stack/deployment-model.json"
    model = json.loads((directory / "stack/base-deployment-model.json").read_text())
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
    print("Production deployment and verification completed", flush=True)


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
    run("docker", "rm", "-f", REGISTRY, check=False)
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
    parser.add_argument("action", choices=("prepare", "redeploy", "cleanup"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.action == "prepare":
        prepare(args.directory)
    elif args.action == "redeploy":
        redeploy(args.directory, args.restore)
    else:
        cleanup(args.directory)
