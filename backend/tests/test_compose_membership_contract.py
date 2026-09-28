"""Render both application deployment paths without using local credentials."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


@pytest.mark.parametrize("filename", ["docker-compose.yml", "docker-compose.swarm.yml"])
def test_compose_scopes_secrets_and_preserves_service_settings(tmp_path, filename):
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose is required for deployment contract checks")
    source = ROOT / filename
    fixture = {
        "MQTT_USE_AUTH": "true",
        "MQTT_USERNAME": "fixture-proxy",
        "MQTT_APIKEY": "fixture-proxy-password",
        "MQTT_CA_FILE": "/certs/proxy-ca.pem",
        "RADAR_MQTT_USE_AUTH": "true",
        "RADAR_MQTT_USERNAME": "fixture-radar",
        "RADAR_MQTT_API_KEY": "fixture-radar-password",
        "RADAR_MQTT_CA_FILE": "/certs/radar-ca.pem",
        "TACTIC_RADAR_DEFAULT_MQTT_USERNAME": "fixture-managed-radar",
        "SYNC_HOSTNAME": "schema-service",
        "SYNC_API_PORT": "9009",
        "SIMULATOR_BROKER_HOST": "fixture-broker",
        "SIMULATOR_INTERVAL_SECONDS": "2.5",
        "SIMULATOR_USERNAME": "fixture-simulator",
        "SIMULATOR_API_KEY": "fixture-simulator-password",
    }
    env_file = tmp_path / ".env"
    env_file.write_text(
        (ROOT / ".env.example").read_text()
        + "\n"
        + "\n".join(f"{key}={value}" for key, value in fixture.items())
    )
    env = os.environ.copy()
    for key in re.findall(r"\$\{([A-Z][A-Z0-9_]*)", source.read_text()):
        env.pop(key, None)
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(env_file),
            "--profile",
            "*",
            "-f",
            str(source),
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    services = json.loads(result.stdout)["services"]
    for key in ("JWT_SECRET", "INTERNAL_API_SECRET", "EMAIL_PASSWORD"):
        assert {
            name
            for name, service in services.items()
            if key in service.get("environment", {})
        } == {"api-gateway", "tactic-middleware"}
    assert all(
        key.startswith("VITE_") or key == "API_UPSTREAM"
        for key in services["frontend"]["environment"]
    )
    expected = {
        "api-gateway": ("SYNC_HOSTNAME", "SYNC_API_PORT"),
        "mqtt-proxy": ("MQTT_USERNAME", "MQTT_APIKEY", "MQTT_CA_FILE"),
        "tactic-middleware": ("TACTIC_RADAR_DEFAULT_MQTT_USERNAME",),
    }
    if filename == "docker-compose.yml":
        expected["mqtt-radar"] = (
            "RADAR_MQTT_USERNAME",
            "RADAR_MQTT_API_KEY",
            "RADAR_MQTT_CA_FILE",
        )
        expected["mqtt-simulator"] = (
            "SIMULATOR_BROKER_HOST",
            "SIMULATOR_INTERVAL_SECONDS",
            "SIMULATOR_USERNAME",
            "SIMULATOR_API_KEY",
        )
    for service, keys in expected.items():
        for key in keys:
            assert services[service]["environment"][key] == fixture[key]
