"""Tie every orchestrator and deploy-gate probe URL to a route its service serves."""

import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
import yaml
from httpx import ASGITransport, AsyncClient
from off_key_core.config.service_auth import get_service_auth_settings
from off_key_db_sync import api as db_sync_api
from off_key_mqtt_proxy.health_api import ProxyHealthApp
from off_key_tactic_middleware.main import create_app

from tests.support.env import AUTH_ENVIRONMENT, EMAIL_ENVIRONMENT, set_environment
from tests.support.runtime_cache import reset_runtime_caches_for_tests

ROOT = Path(__file__).resolve().parents[2]
URL = re.compile(r"https?://[^'\"\s]+")
# Compose service and deploy-gate host for each probed application.
SERVICES = {
    "api-gateway": "api",
    "tactic-middleware": "tactic",
    "mqtt-proxy": "localhost",
    "db-sync": "db-sync",
}


def _healthcheck_paths(compose_file):
    services = yaml.safe_load((ROOT / compose_file).read_text())["services"]
    return {
        name: urlsplit(URL.search(service["healthcheck"]["test"][-1])[0]).path
        for name, service in services.items()
        if name in SERVICES and "healthcheck" in service
    }


def _deploy_gate_paths():
    spec = importlib.util.spec_from_file_location(
        "check_application", ROOT / "infra/scripts/check_application.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    hosts = {host: name for name, host in SERVICES.items()}
    return {
        hosts[url.hostname]: url.path
        for url in map(urlsplit, module.probe_endpoints({}).values())
    }


def _probes():
    return sorted(
        set(_healthcheck_paths("docker-compose.yml").items())
        | set(_healthcheck_paths("infra/stack/docker-compose.swarm.yml").items())
        | set(_deploy_gate_paths().items())
    )


def test_every_probed_service_is_covered():
    assert {name for name, _ in _probes()} == set(SERVICES)
    assert len(_deploy_gate_paths()) == len(SERVICES)


@pytest.fixture
def applications(monkeypatch):
    set_environment(
        monkeypatch,
        {
            **AUTH_ENVIRONMENT,
            **EMAIL_ENVIRONMENT,
            "INTERNAL_API_SECRET": "test-internal-service-secret-123456789",
            "APP_NAME": "off-key-test",
            "DEBUG": "false",
            "ANOMALY_ALERT_RECIPIENTS": "admin@example.com",
        },
    )
    monkeypatch.setattr(
        "off_key_core.config.env.load_dotenv", lambda *args, **kwargs: False
    )
    reset_runtime_caches_for_tests()
    get_service_auth_settings.cache_clear()
    from off_key_api_gateway.main import app as gateway

    proxy = SimpleNamespace(
        is_running=True, get_readiness_status=lambda: {"ready": proxy.ready}
    )
    tactic = create_app()
    readiness = {
        "api-gateway": lambda ready: None,
        "tactic-middleware": lambda ready: (
            setattr(tactic.state, "model_registry_ready", ready),
            setattr(tactic.state, "docker_client", object() if ready else None),
        ),
        "mqtt-proxy": lambda ready: setattr(proxy, "ready", ready),
        "db-sync": lambda ready: db_sync_api.set_sync_service(
            SimpleNamespace(schema_ready=ready)
        ),
    }
    yield (
        {
            "api-gateway": gateway,
            "tactic-middleware": tactic,
            "mqtt-proxy": ProxyHealthApp(proxy),
            "db-sync": db_sync_api.app,
        },
        readiness,
    )
    db_sync_api.set_sync_service(None)
    reset_runtime_caches_for_tests()
    get_service_auth_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("name,path", _probes())
async def test_probe_answers_ready_only_when_service_is_ready(applications, name, path):
    apps, set_ready = applications
    async with AsyncClient(
        transport=ASGITransport(app=apps[name]), base_url="http://test"
    ) as client:
        set_ready[name](False)
        not_ready = await client.get(path)
        set_ready[name](True)
        ready = await client.get(path)

    # The gateway probe is liveness only; readiness probes must gate on state.
    expected = 200 if name == "api-gateway" else 503
    assert not_ready.status_code == expected, not_ready.text
    assert ready.status_code == 200, ready.text
