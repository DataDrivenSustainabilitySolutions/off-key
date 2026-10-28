"""Check the local deployment contract without starting containers or collectors."""

import argparse
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from tests.support.compose import load_compose

ROOT = Path(__file__).parents[3]


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "local_deployment", ROOT / "dev/local/run.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checkout = tmp_path / "checkout"
    local = checkout / "dev/local"
    local.mkdir(parents=True)
    for relative in (
        ".env.example",
        "docker-compose.yml",
        "dev/local/compose.yml",
        "dev/local/compose.live-tailnet.yml",
    ):
        shutil.copyfile(ROOT / relative, checkout / relative)
    monkeypatch.setattr(module, "ROOT", checkout)
    monkeypatch.setattr(module, "LOCAL", local)
    monkeypatch.setattr(module, "ENV_FILE", local / ".env")
    # Never change the developer's or CI's Docker engine from a contract test.
    monkeypatch.setattr(module, "ensure_swarm", lambda environment: None)
    module.initialize(
        argparse.Namespace(
            project=None,
            frontend_port=5174,
            api_port=8002,
            admin_email="admin@example.com",
        )
    )
    return module


def test_init_preserves_private_configuration(launcher):
    values = launcher.read_environment(launcher.ENV_FILE)
    original = launcher.ENV_FILE.read_bytes()
    assert stat.S_IMODE(launcher.ENV_FILE.stat().st_mode) == 0o600
    secrets = [
        values[key]
        for key in (
            "JWT_SECRET",
            "INTERNAL_API_SECRET",
            "POSTGRES_PASSWORD",
            "EMQX_DASHBOARD_PASSWORD",
        )
    ]
    assert len(set(secrets)) == len(secrets)
    assert all(len(value) >= 32 for value in secrets)
    assert json.loads(values["SYSTEM_BROKER_ROUTES"]) == [
        {
            "name": "local",
            "hosts": ["source-broker"],
            "socks_proxy": {"host": "broker-route", "port": 1055},
        }
    ]
    assert values["POSTGRES_PORT"] == "5432"
    assert values["TACTIC_RADAR_WORKLOAD_LIFECYCLE"] == "persistent"
    assert values["SYSTEM_LIVE_ENABLED"] == "true"
    assert json.loads(values["SYSTEM_LIVE_ALLOWED_HOSTS"]) == launcher.LOCAL_LIVE_HOSTS
    assert values["SYSTEM_LIVE_CREDENTIALS"] == "{}"
    assert launcher.default_project(launcher.ROOT) != launcher.default_project(
        launcher.ROOT.parent
    )
    launcher.initialize(argparse.Namespace(project="unused", frontend_port=5999))
    assert launcher.ENV_FILE.read_bytes() == original


def test_commands_ignore_exported_credentials_and_unconfigured_optional_secrets(
    launcher,
    monkeypatch,
):
    calls = []
    monkeypatch.setenv("POSTGRES_PASSWORD", "exported-production-password")
    monkeypatch.setenv("JWT_SECRET", "exported-production-jwt")
    monkeypatch.setenv("MQTT_APIKEY", "exported-production-mqtt")
    monkeypatch.setenv("COMPOSE_PROFILES", "radar-image")
    monkeypatch.setenv("DOCKER_HOST", "unix:///var/run/docker.sock")
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setattr(
        launcher.subprocess, "run", lambda *args, **kwargs: calls.append((args, kwargs))
    )
    command = [*launcher.compose_command(all_profiles=True), "stop"]
    launcher.execute(command)
    arguments, options = calls[0]
    assert arguments[0] == command
    assert options["cwd"] == launcher.ROOT
    assert options["check"] is True
    assert (
        not {"POSTGRES_PASSWORD", "JWT_SECRET", "MQTT_APIKEY", "COMPOSE_PROFILES"}
        & options["env"].keys()
    )
    assert "--env-file" in command
    assert command[-1] == "stop"
    assert "down" not in command


def test_tailnet_is_opt_in_and_does_not_accept_ambient_image_settings(
    launcher, monkeypatch
):
    assert not any("compose.live-tailnet" in arg for arg in launcher.compose_command())
    with launcher.ENV_FILE.open("a") as file:
        file.write("LOCAL_LIVE_TAILNET_ENABLED=true\n")
    assert (
        str(launcher.LOCAL / "compose.live-tailnet.yml") in launcher.compose_command()
    )
    monkeypatch.setenv("LOCAL_LIVE_TAILNET_IMAGE", "unexpected-image")
    assert "LOCAL_LIVE_TAILNET_IMAGE" not in launcher.deployment_environment()


def test_tailnet_login_uses_only_its_local_container_and_explicit_server(
    launcher, monkeypatch
):
    with launcher.ENV_FILE.open("a") as file:
        file.write(
            "LOCAL_LIVE_TAILNET_ENABLED=true\nLOCAL_LIVE_TAILNET_LOGIN_SERVER=https://vpn.example.com\n"
        )
    calls = []
    monkeypatch.setattr(launcher, "execute", lambda command: calls.append(command))
    launcher.tailnet_login(launcher.compose_command())
    assert calls[0][-6:] == [
        "tailscale",
        "up",
        "--login-server=https://vpn.example.com",
        "--hostname="
        + launcher.read_environment(launcher.ENV_FILE)["COMPOSE_PROJECT_NAME"]
        + "-live",
        "--accept-dns=false",
        "--timeout=15s",
    ]
    assert calls[0][calls[0].index("exec") + 2] == "live-tailnet"


@pytest.mark.parametrize(
    "server",
    [
        "",
        "http://vpn.example.com",
        "https://user:secret@vpn.example.com",
        "https://vpn.example.com/?token=secret",
    ],
)
def test_tailnet_login_rejects_missing_or_credential_bearing_server(
    launcher, monkeypatch, server
):
    with launcher.ENV_FILE.open("a") as file:
        file.write(
            "LOCAL_LIVE_TAILNET_ENABLED=true\nLOCAL_LIVE_TAILNET_LOGIN_SERVER="
            + server
            + "\n"
        )
    calls = []
    monkeypatch.setattr(launcher, "execute", lambda command: calls.append(command))
    with pytest.raises(ValueError, match="HTTPS"):
        launcher.tailnet_login(launcher.compose_command())
    assert not calls


@pytest.mark.parametrize(
    "endpoint, local",
    [
        ("unix:///var/run/docker.sock", True),
        ("unix:///run/user/1000/docker.sock", True),
        ("unix:///Users/test/.docker/run/docker.sock", True),
        ("npipe:////./pipe/dockerDesktopLinuxEngine", True),
        ("tcp://127.0.0.1:2375", True),
        ("tcp://[::1]:2376", True),
        ("tcp://localhost:2375", True),
        ("tcp://10.0.0.2:2376", False),
        ("tcp://production.example.com:2376", False),
        ("ssh://operator@production.example.com", False),
        ("unix://remote.example.com/var/run/docker.sock", False),
        ("npipe:////remote/pipe/docker_engine", False),
        ("", False),
    ],
)
def test_local_endpoint_validation(launcher, endpoint, local):
    assert launcher.is_local_endpoint(endpoint) is local


def test_selected_remote_context_overrides_local_docker_host(launcher, monkeypatch):
    calls = []

    def inspect(command, **options):
        calls.append(command)
        return subprocess.CompletedProcess(
            command, 0, "ssh://operator@production.example.com\n"
        )

    monkeypatch.setattr(launcher.subprocess, "run", inspect)
    with pytest.raises(ValueError, match="local Docker"):
        launcher.ensure_local_docker(
            {
                "DOCKER_CONTEXT": "production",
                "DOCKER_HOST": "unix:///var/run/docker.sock",
            }
        )
    assert calls == [
        [
            "docker",
            "context",
            "inspect",
            "production",
            "--format",
            "{{.Endpoints.docker.Host}}",
        ]
    ]


@pytest.mark.parametrize("failure", [False, True])
def test_public_image_mode_preserves_context_and_private_config(
    launcher,
    monkeypatch,
    tmp_path,
    failure,
):
    saved = tmp_path / "saved-docker"
    saved.mkdir()
    original = '{"credsStore":"desktop","auths":{"private.example.com":{}}}'
    (saved / "config.json").write_text(original)
    plugins = saved / "cli-plugins"
    plugins.mkdir()
    for name in ("docker-compose", "docker-buildx"):
        (plugins / name).write_text("installed plugin binary")
    monkeypatch.setenv("DOCKER_CONFIG", str(saved))
    monkeypatch.setenv("DOCKER_CONTEXT", "desktop-linux")
    monkeypatch.setenv("DOCKER_HOST", "tcp://production.example.com:2376")
    endpoint = "unix:///Users/test/.docker/run/docker.sock"
    inspections, phases = [], []

    def inspect(command, **options):
        inspections.append((command, options["env"]))
        return subprocess.CompletedProcess(command, 0, endpoint + "\n")

    monkeypatch.setattr(launcher.subprocess, "run", inspect)

    def phase(command, environment):
        directory = Path(environment["DOCKER_CONFIG"])
        assert directory != saved
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        assert json.loads((directory / "config.json").read_text()) == {}
        assert {file.name for file in directory.iterdir()} == {
            "config.json",
            "cli-plugins",
        }
        assert {file.name for file in (directory / "cli-plugins").iterdir()} == {
            "docker-compose",
            "docker-buildx",
        }
        for name in ("docker-compose", "docker-buildx"):
            assert (
                directory / "cli-plugins" / name
            ).read_text() == "installed plugin binary"
        assert environment["DOCKER_HOST"] == endpoint
        assert "DOCKER_CONTEXT" not in environment
        phases.append((command, directory))
        if failure:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(launcher, "execute", phase)
    command = launcher.compose_command()
    if failure:
        with pytest.raises(subprocess.CalledProcessError):
            launcher.start_stack(command, public_images=True)
    else:
        launcher.start_stack(command, public_images=True)
        assert len(phases) == 2
        assert phases[0][1] == phases[1][1]
        assert phases[0][0][-2:] == ["build", "mqtt-radar"]
        assert "--profile" not in phases[1][0]
    assert inspections[0][0][3] == "desktop-linux"
    assert inspections[0][1]["DOCKER_CONFIG"] == str(saved)
    assert not phases[0][1].exists()
    assert (saved / "config.json").read_text() == original
    assert os.environ["DOCKER_CONFIG"] == str(saved)
    assert os.environ["DOCKER_CONTEXT"] == "desktop-linux"


def test_regular_start_preserves_docker_configuration(launcher, monkeypatch):
    monkeypatch.setenv("DOCKER_CONFIG", "/original/docker-config")
    monkeypatch.setenv("DOCKER_CONTEXT", "desktop-linux")
    phases = []
    monkeypatch.setattr(
        launcher, "execute", lambda command, environment: phases.append(environment)
    )
    launcher.start_stack(launcher.compose_command(), public_images=False)
    assert len(phases) == 2
    assert all(phase["DOCKER_CONFIG"] == "/original/docker-config" for phase in phases)
    assert all(phase["DOCKER_CONTEXT"] == "desktop-linux" for phase in phases)


def test_broker_fixture_is_explicit_and_preserves_existing_allowlist(
    launcher, monkeypatch
):
    phases = []
    original = launcher.ENV_FILE.read_bytes()
    monkeypatch.setattr(
        launcher, "execute", lambda command, environment: phases.append(command)
    )
    launcher.start_stack(
        launcher.compose_command(),
        public_images=False,
        broker_fixture=True,
    )
    assert phases[1][phases[1].index("--profile") + 1] == "broker-fixture"
    assert launcher.ENV_FILE.read_bytes() == original


def test_local_compose_builds_current_artifacts_and_isolates_services(launcher):
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose is required for deployment contract checks")
    environment = os.environ.copy()
    sources = (launcher.ROOT / "docker-compose.yml").read_text() + (
        launcher.LOCAL / "compose.yml"
    ).read_text()
    for key in set(launcher.read_environment(launcher.ENV_FILE)) | set(
        re.findall(r"\$\{([A-Z][A-Z0-9_]*)", sources)
    ):
        environment.pop(key, None)
    result = subprocess.run(
        [*launcher.compose_command(all_profiles=True), "config", "--format", "json"],
        cwd=launcher.ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    deployment = json.loads(result.stdout)
    services = deployment["services"]
    project = launcher.read_environment(launcher.ENV_FILE)["COMPOSE_PROJECT_NAME"]
    assert deployment["name"] == project
    assert (
        services["socket-proxy"]["image"]
        == "ghcr.io/tecnativa/docker-socket-proxy:v0.4.2"
    )
    for service in services.values():
        assert "container_name" not in service
        assert all(port["host_ip"] == "127.0.0.1" for port in service.get("ports", []))
        if "build" in service:
            assert service["image"].startswith(f"{project}-")
            assert service["build"]["context"].startswith(str(launcher.ROOT))
    assert all(
        volume["name"].startswith(f"{project}_")
        for volume in deployment["volumes"].values()
    )
    assert services["frontend"]["build"]["target"] == "production"
    assert services["frontend"]["build"]["args"] == {
        "VITE_LOCAL_ADMIN_EMAIL": "admin@example.com",
    }
    assert "--reload" not in services["api-gateway"]["command"]
    assert "develop" not in services["frontend"]
    assert services["frontend"]["environment"] == {"API_UPSTREAM": "api-gateway:8000"}
    assert (
        services["tactic-middleware"]["environment"]["TACTIC_RADAR_WORKLOAD_LIFECYCLE"]
        == "persistent"
    )
    assert json.loads(
        services["tactic-middleware"]["environment"]["SYSTEM_BROKER_ROUTES"]
    ) == [
        {
            "name": "local",
            "hosts": ["source-broker"],
            "socks_proxy": {"host": "broker-route", "port": 1055},
        }
    ]
    assert (
        services["frontend"]["depends_on"]["api-gateway"]["condition"]
        == "service_healthy"
    )
    mail_volume = services["mailpit"]["volumes"][0]
    assert mail_volume["type"] == "volume"
    assert mail_volume["source"] == "local_mailpit_data"
    assert services["mailpit"]["environment"]["MP_DATABASE"] == "/data/mailpit.db"
    assert not any(
        ".tmp/spatial-runtime" in str(service) for service in services.values()
    )
    fixture_names = set(launcher.LOCAL_LIVE_HOSTS) - {"source-broker"}
    for name in fixture_names | {"broker-fixture-publisher"}:
        assert services[name]["profiles"] == ["broker-fixture"]
        assert services[name].get("ports", []) == []
        assert set(services[name]["networks"]) == {"app-network"}
    assert set(services["broker-fixture-publisher"]["depends_on"]) == fixture_names


def test_compose_defaults_follow_the_launcher_and_the_fixture_brokers(launcher):
    """compose.yml repeats run.PORTS, the live allowlist and broker_fixture hosts."""
    text = (ROOT / "dev/local/compose.yml").read_text()
    defaults = {
        name: int(port)
        for name, port in re.findall(r"\$\{(LOCAL_[A-Z_]+_PORT):-(\d+)\}", text)
    }
    assert defaults == launcher.PORTS
    (allowlist,) = re.findall(r"\$\{SYSTEM_LIVE_ALLOWED_HOSTS:-(.+?)\}'", text)
    assert allowlist == json.dumps(launcher.LOCAL_LIVE_HOSTS, separators=(",", ":"))
    services = load_compose(ROOT / "dev/local/compose.yml")["services"]
    fixture_hosts = set(launcher.LOCAL_LIVE_HOSTS) - {"source-broker"}
    assert {name for name in services if name.startswith("fixture-broker-")} == (
        fixture_hosts
    )
    assert set(services["broker-fixture-publisher"]["depends_on"]) == fixture_hosts


@pytest.mark.parametrize(
    ("state", "initialized"),
    [("active true", False), ("inactive false", True), ("active false", None)],
)
def test_local_start_requires_a_swarm_manager(
    tmp_path, monkeypatch, state, initialized
):
    spec = importlib.util.spec_from_file_location(
        "local_swarm", ROOT / "dev/local/run.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=f"{state}\n")

    monkeypatch.setattr(module, "ensure_local_docker", lambda environment: None)
    monkeypatch.setattr(module.subprocess, "run", run)
    if initialized is None:
        with pytest.raises(ValueError, match="Swarm manager"):
            module.ensure_swarm({})
        return
    module.ensure_swarm({})
    init = ["docker", "swarm", "init", "--advertise-addr", "127.0.0.1"]
    assert (init in calls) is initialized


def test_demo_option_opens_guest_browsing_and_allows_the_demo_brokers(launcher):
    launcher.ENV_FILE.unlink()
    launcher.initialize(
        argparse.Namespace(
            project=None,
            frontend_port=5174,
            api_port=8002,
            admin_email="admin@example.com",
            demo=True,
        )
    )
    values = launcher.read_environment(launcher.ENV_FILE)
    assert values["DEMO_MODE"] == "true"
    assert values["DEMO_VIEWER_EMAIL"] == launcher.DEMO_VIEWER_EMAIL
    assert len(values["DEMO_VIEWER_PASSWORD"]) >= 32
    assert json.loads(values["SYSTEM_LIVE_ALLOWED_HOSTS"]) == [
        *launcher.LOCAL_LIVE_HOSTS,
        *launcher.DEMO_HOSTS,
    ]


def test_demo_option_enables_an_existing_configuration_once(launcher):
    before = launcher.read_environment(launcher.ENV_FILE)
    assert before["DEMO_MODE"] == "false"
    enable = argparse.Namespace(project=None, demo=True)
    launcher.initialize(enable)
    enabled = launcher.read_environment(launcher.ENV_FILE)
    changed = {key for key in before if before[key] != enabled.get(key)}
    assert changed == {
        "DEMO_MODE",
        "DEMO_VIEWER_EMAIL",
        "DEMO_VIEWER_PASSWORD",
        "SYSTEM_LIVE_ALLOWED_HOSTS",
    }
    assert stat.S_IMODE(launcher.ENV_FILE.stat().st_mode) == 0o600
    launcher.initialize(enable)
    assert launcher.read_environment(launcher.ENV_FILE) == enabled


def test_demo_command_loads_the_catalogue_and_passes_the_password_by_name(
    launcher, monkeypatch
):
    with pytest.raises(ValueError, match="init --demo"):
        launcher.open_demo(launcher.compose_command())
    launcher.initialize(argparse.Namespace(project=None, demo=True))
    password = launcher.read_environment(launcher.ENV_FILE)["DEMO_VIEWER_PASSWORD"]
    catalogue = launcher.ROOT / launcher.DEMO_CATALOGUE
    catalogue.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / launcher.DEMO_CATALOGUE, catalogue)
    monkeypatch.setattr(launcher, "ensure_local_docker", lambda environment: "")
    calls = []

    def run(command, **options):
        calls.append((command, options))
        status = "loaded" if "bootstrap_demo_catalogue" in command[-1] else "waiting"
        return subprocess.CompletedProcess(command, 0, json.dumps({"status": status}))

    monkeypatch.setattr(launcher.subprocess, "run", run)
    launcher.open_demo(launcher.compose_command())
    (load, load_options), (viewer, viewer_options) = calls
    assert load_options["input"] == catalogue.read_text(encoding="utf-8")
    assert load[-1] == "off_key_tactic_middleware.bootstrap_demo_catalogue"
    assert viewer[-1] == "off_key_tactic_middleware.bootstrap_demo_viewer"
    assert all(password not in part for part in viewer)
    assert viewer_options["env"]["DEMO_VIEWER_PASSWORD"] == password
