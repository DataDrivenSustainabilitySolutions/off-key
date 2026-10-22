#!/usr/bin/env python3
"""Run an isolated deployment of this checkout using the real application stack."""

import argparse
import hashlib
import importlib.util
import ipaddress
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from contextlib import contextmanager, nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / "dev" / "local"
ENV_FILE = LOCAL / ".env"
API_KEYS = LOCAL / "state" / "emqx-api-keys"


def _load_broker_fixture():
    """Load the sibling fixture module by path, whoever imports this launcher."""
    spec = importlib.util.spec_from_file_location(
        "broker_fixture", LOCAL / "broker_fixture.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The source broker plus every fixture broker; compose.yml repeats this list as
# its allowlist default, pinned by the local deployment contract test.
LOCAL_LIVE_HOSTS = [
    "source-broker",
    *(broker.host for broker in _load_broker_fixture().BROKERS),
]

PORTS = {
    "LOCAL_FRONTEND_PORT": 5174,
    "LOCAL_API_PORT": 8002,
    "LOCAL_TACTIC_PORT": 8003,
    "LOCAL_POSTGRES_PORT": 5433,
    "LOCAL_MAILPIT_PORT": 8026,
    "LOCAL_SMTP_PORT": 1026,
    "LOCAL_MQTT_PORT": 1885,
    "LOCAL_MQTT_WS_PORT": 8085,
    "LOCAL_MQTT_WSS_PORT": 8086,
    "LOCAL_MQTT_TLS_PORT": 8885,
    "LOCAL_EMQX_PORT": 18084,
    "LOCAL_SOURCE_MQTT_PORT": 1886,
}


def default_project(root: Path) -> str:
    suffix = hashlib.sha256(str(root.resolve()).encode()).hexdigest()[:10]
    return f"offkey-local-{suffix}"


def read_environment(path: Path) -> dict[str, str]:
    """Read generated dotenv values without executing shell expressions."""
    values = {}
    for line in path.read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            key, separator, value = line.partition("=")
            if separator:
                values[key.strip()] = value.strip().strip("'\"")
    return values


def private_write(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(content)


def initialize(args: argparse.Namespace) -> None:
    if ENV_FILE.exists():
        print("Existing local configuration preserved.")
        return
    if API_KEYS.exists():
        raise ValueError(
            "Local API keys already exist. Restore the matching .env first."
        )

    project = args.project or default_project(ROOT)
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project):
        raise ValueError("Project names must use lowercase letters, digits, _ or -.")
    values = read_environment(ROOT / ".env.example")
    ports = {
        **PORTS,
        "LOCAL_FRONTEND_PORT": args.frontend_port,
        "LOCAL_API_PORT": args.api_port,
    }
    if len(set(ports.values())) != len(ports):
        raise ValueError("Local service ports must be distinct.")
    values.update({key: str(value) for key, value in ports.items()})
    origin = f"http://127.0.0.1:{args.frontend_port}"
    values.update(
        COMPOSE_PROJECT_NAME=project,
        FRONTEND_BASE_URL=origin,
        CORS_ALLOWED_ORIGINS=f'["{origin}"]',
        POSTGRES_PORT="5432",
        SUPERUSER_MAIL=args.admin_email,
        AMBIBOX_ALLOWED_HOSTS='["source-broker"]',
        AMBIBOX_ALLOWED_HOST_SUFFIXES="[]",
        AMBIBOX_EMQX_API_KEY=f"{project}-controller",
        SIMULATOR_CHARGER_IDS="charger-sim-1,charger-sim-2",
        SIMULATOR_WORKSHOP_ENABLED="true",
        SYSTEM_LIVE_ENABLED="true",
        SYSTEM_LIVE_ALLOWED_HOSTS=json.dumps(LOCAL_LIVE_HOSTS, separators=(",", ":")),
        SYSTEM_LIVE_CREDENTIALS="{}",
        TACTIC_RADAR_WORKLOAD_LIFECYCLE="persistent",
        LOCAL_SOCKET_PROXY_IMAGE="ghcr.io/tecnativa/docker-socket-proxy:v0.4.2",
    )
    for key in (
        "JWT_SECRET",
        "INTERNAL_API_SECRET",
        "POSTGRES_PASSWORD",
        "EMAIL_PASSWORD",
        "EMQX_DASHBOARD_PASSWORD",
        "EMQX_NODE_COOKIE",
        "AMBIBOX_EMQX_API_SECRET",
        "AMBIBOX_GOST_PASSWORD",
    ):
        values[key] = secrets.token_hex(32)
    for key, service in (
        ("FRONTEND_IMAGE", "frontend"),
        ("API_GATEWAY_IMAGE", "api-gateway"),
        ("TACTIC_MIDDLEWARE_IMAGE", "tactic-middleware"),
        ("DB_SYNC_IMAGE", "db-sync"),
        ("MQTT_RADAR_IMAGE", "mqtt-radar"),
        ("MQTT_PROXY_IMAGE", "mqtt-proxy"),
        ("MQTT_SIMULATOR_IMAGE", "mqtt-simulator"),
    ):
        values[key] = f"{project}-{service}:dev"

    API_KEYS.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_write(
        API_KEYS,
        f"{values['AMBIBOX_EMQX_API_KEY']}:{values['AMBIBOX_EMQX_API_SECRET']}\n",
    )
    # EMQX runs under its own container UID. The 0700 host directory protects
    # this readable, read-only file from other host users.
    API_KEYS.chmod(0o444)
    private_write(
        ENV_FILE,
        "# Private local deployment configuration; do not commit.\n"
        + "\n".join(f"{key}={value}" for key, value in values.items())
        + "\n",
    )
    print(f"Created private configuration for {project}.")
    print(f"After startup: {origin}/")


def compose_command(*, all_profiles: bool = False) -> list[str]:
    if not ENV_FILE.is_file() or not API_KEYS.is_file():
        raise ValueError("Run `python3 dev/local/run.py init` first.")
    values = read_environment(ENV_FILE)
    project = values.get("COMPOSE_PROJECT_NAME", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", project):
        raise ValueError("Invalid or missing COMPOSE_PROJECT_NAME in local .env.")
    command = [
        "docker",
        "compose",
        "--project-name",
        project,
        "--env-file",
        str(ENV_FILE),
        "-f",
        str(ROOT / "docker-compose.yml"),
        "-f",
        str(LOCAL / "compose.yml"),
    ]
    if values.get("LOCAL_LIVE_TAILNET_ENABLED", "false").lower() == "true":
        command.extend(["-f", str(LOCAL / "compose.live-tailnet.yml")])
    if values.get("LOCAL_CATALOG_FIXTURE_ENABLED", "false").lower() == "true":
        fixture = LOCAL / "state" / "catalog-fixture.compose.json"
        if not fixture.is_file():
            raise ValueError(
                "Generate the private catalogue fixture before enabling it."
            )
        command.extend(["-f", str(fixture)])
    if all_profiles:
        command.extend(["--profile", "*"])
    return command


def is_local_endpoint(endpoint: str) -> bool:
    """Accept Docker's local sockets and explicit loopback TCP endpoints."""
    try:
        address = urlsplit(endpoint)
        if address.username is not None or address.password is not None:
            return False
        if address.scheme == "unix":
            return not address.netloc and address.path.startswith("/")
        if address.scheme == "npipe":
            return not address.netloc and address.path.startswith("//./pipe/")
        if address.scheme not in {"tcp", "http", "https"}:
            return False
        if address.hostname == "localhost":
            return True
        return ipaddress.ip_address(address.hostname or "").is_loopback
    except ValueError:
        return False


def ensure_local_docker(environment: dict[str, str]) -> str:
    # Docker's context selection takes precedence over DOCKER_HOST. Inspect
    # that same selection before any command that can change containers.
    context = environment.get("DOCKER_CONTEXT")
    endpoint = environment.get("DOCKER_HOST") if not context else None
    if not endpoint:
        inspection = ["docker", "context", "inspect"]
        if context:
            inspection.append(context)
        inspection.extend(["--format", "{{.Endpoints.docker.Host}}"])
        endpoint = subprocess.run(
            inspection,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    if not is_local_endpoint(endpoint):
        raise ValueError(
            "This workflow requires a local Docker socket or loopback endpoint. "
            "Select your local Docker context first."
        )
    return endpoint


def deployment_environment() -> dict[str, str]:
    # Keep ambient deployment variables from overriding this checkout's private
    # dotenv configuration. Do not alter the caller's shell environment.
    environment = os.environ.copy()
    interpolated = set(
        re.findall(
            r"\$\{([A-Z][A-Z0-9_]*)",
            (ROOT / "docker-compose.yml").read_text()
            + (LOCAL / "compose.yml").read_text()
            + (LOCAL / "compose.live-tailnet.yml").read_text(),
        )
    )
    for key in set(read_environment(ENV_FILE)) | interpolated:
        environment.pop(key, None)
    for key in PORTS:
        environment.pop(key, None)
    environment.pop("COMPOSE_PROFILES", None)
    return environment


@contextmanager
def public_image_environment(environment: dict[str, str]):
    # Resolve the selected context before replacing Docker's config directory.
    # An empty temporary config avoids credential-helper calls for public images.
    endpoint = ensure_local_docker(environment)
    with TemporaryDirectory(prefix="offkey-local-docker-") as directory:
        private_write(Path(directory) / "config.json", "{}\n")
        # Desktop installs Compose/buildx under its config directory. Expose
        # those binaries alone; never copy saved auth or credential settings.
        installed = (
            Path(environment.get("DOCKER_CONFIG", str(Path.home() / ".docker")))
            / "cli-plugins"
        )
        for name in ("docker-compose", "docker-buildx"):
            candidate = installed / name
            if not candidate.is_file():
                executable = shutil.which(name, path=environment.get("PATH"))
                if not executable:
                    continue
                candidate = Path(executable)
            destination = Path(directory) / "cli-plugins" / name
            destination.parent.mkdir(mode=0o700, exist_ok=True)
            if os.name == "nt":
                shutil.copyfile(candidate, destination)
            else:
                destination.symlink_to(candidate.resolve())
        scoped = {**environment, "DOCKER_CONFIG": directory, "DOCKER_HOST": endpoint}
        scoped.pop("DOCKER_CONTEXT", None)
        yield scoped


def execute(command: list[str], environment: dict[str, str] | None = None) -> None:
    if environment is None:
        environment = deployment_environment()
    ensure_local_docker(environment)
    subprocess.run(command, cwd=ROOT, env=environment, check=True)


def ensure_swarm(environment: dict[str, str]) -> None:
    """TACTIC runs RADAR as Swarm services, so the local engine must manage one."""
    ensure_local_docker(environment)
    state = subprocess.run(
        [
            "docker",
            "info",
            "--format",
            "{{.Swarm.LocalNodeState}} {{.Swarm.ControlAvailable}}",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout.split()
    if state == ["active", "true"]:
        return
    if state[:1] != ["inactive"]:
        raise ValueError(
            "RADAR needs this Docker engine to be a Swarm manager; "
            f"its Swarm state is {' '.join(state) or 'unknown'}."
        )
    print("Starting a single-node Docker Swarm for RADAR workloads.")
    subprocess.run(
        ["docker", "swarm", "init", "--advertise-addr", "127.0.0.1"],
        env=environment,
        timeout=60,
        check=True,
    )


def start_stack(
    command: list[str],
    *,
    simulator: bool,
    public_images: bool,
    broker_fixture: bool = False,
) -> None:
    environment = deployment_environment()
    scope = (
        public_image_environment(environment)
        if public_images
        else nullcontext(environment)
    )
    with scope as scoped:
        ensure_swarm(scoped)
        execute([*command, "build", "mqtt-radar"], scoped)
        profile = ["--profile", "mqtt-sim"] if simulator else []
        if broker_fixture:
            profile.extend(["--profile", "broker-fixture"])
        execute([*command, *profile, "up", "--build", "--detach", "--wait"], scoped)
    if broker_fixture:
        print("Import dev/local/broker-system.json, then choose Connect.")
        print(
            "Existing local .env files keep their allowlist; include the fixture hosts."
        )


def port(value: str) -> int:
    number = int(value)
    if not 1024 <= number <= 65535:
        raise argparse.ArgumentTypeError("Use an unprivileged port from 1024 to 65535.")
    return number


def tailnet_login(command: list[str]) -> None:
    values = read_environment(ENV_FILE)
    if values.get("LOCAL_LIVE_TAILNET_ENABLED", "false").lower() != "true":
        raise ValueError("Set LOCAL_LIVE_TAILNET_ENABLED=true in dev/local/.env first.")
    server = values.get("LOCAL_LIVE_TAILNET_LOGIN_SERVER", "")
    address = urlsplit(server)
    if (
        address.scheme != "https"
        or not address.hostname
        or address.username is not None
        or address.password is not None
        or address.query
        or address.fragment
        or address.path not in {"", "/"}
        or any(ord(character) < 33 for character in server)
    ):
        raise ValueError("Set a valid HTTPS LOCAL_LIVE_TAILNET_LOGIN_SERVER.")
    hostname = values.get(
        "LOCAL_LIVE_TAILNET_HOSTNAME", values["COMPOSE_PROJECT_NAME"] + "-live"
    )
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,61}[a-z0-9]", hostname):
        raise ValueError(
            "Use a local tailnet hostname with 2–63 letters/digits/hyphens."
        )
    execute(
        [
            *command,
            "exec",
            "-T",
            "live-tailnet",
            "tailscale",
            "up",
            "--login-server=" + server,
            "--hostname=" + hostname,
            "--accept-dns=false",
            "--timeout=15s",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create private local configuration once")
    init.add_argument("--project")
    init.add_argument(
        "--frontend-port", type=port, default=PORTS["LOCAL_FRONTEND_PORT"]
    )
    init.add_argument("--api-port", type=port, default=PORTS["LOCAL_API_PORT"])
    init.add_argument("--admin-email", default="admin@example.com")
    up = commands.add_parser("up", help="Build this checkout and start the stack")
    up.add_argument("--simulator", action="store_true", help="Publish local MQTT data")
    up.add_argument(
        "--broker-fixture",
        action="store_true",
        help="Run six real MQTT brokers with 39 synthetic entities",
    )
    up.add_argument(
        "--public-images",
        action="store_true",
        help="Pull public images anonymously with a temporary empty Docker config",
    )
    commands.add_parser("status", help="Show local deployment service health")
    logs = commands.add_parser("logs", help="Show the last 100 service log lines")
    logs.add_argument("services", nargs="*")
    logs.add_argument("--follow", action="store_true")
    commands.add_parser("stop", help="Stop services and preserve database/broker data")
    commands.add_parser(
        "tailnet-login", help="Register the separate local tailnet device"
    )
    admin = commands.add_parser(
        "bootstrap-admin", help="Send invitation to local Mailpit"
    )
    admin.add_argument("--resend", action="store_true")
    args = parser.parse_args()
    if args.command == "init":
        initialize(args)
        return
    command = compose_command(all_profiles=args.command in {"status", "logs", "stop"})
    if args.command == "up":
        start_stack(
            command,
            simulator=args.simulator,
            public_images=args.public_images,
            broker_fixture=args.broker_fixture,
        )
    elif args.command == "status":
        execute(command + ["ps", "--all"])
    elif args.command == "logs":
        execute(
            command
            + ["logs", "--tail", "100"]
            + (["--follow"] if args.follow else [])
            + args.services
        )
    elif args.command == "stop":
        execute(command + ["stop"])
    elif args.command == "tailnet-login":
        tailnet_login(command)
    else:
        execute(
            command
            + [
                "exec",
                "-T",
                "tactic-middleware",
                "/app/bin/python",
                "-m",
                "off_key_tactic_middleware.bootstrap_admin",
                "--send-email",
            ]
            + (["--resend"] if args.resend else [])
        )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"Local deployment: {error}", file=sys.stderr)
        sys.exit(1)
