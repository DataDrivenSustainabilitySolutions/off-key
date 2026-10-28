"""Tests for reliable TACTIC startup and shutdown resource handling."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from off_key_tactic_middleware.config import RadarWorkloadLifecycle

tactic_main = import_module("off_key_tactic_middleware.main")
radar_workloads = import_module(
    "off_key_tactic_middleware.services.orchestration.radar_workloads"
)


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        radar_workload_lifecycle=RadarWorkloadLifecycle.EPHEMERAL,
        reconciliation_enabled=True,
        reconciliation_interval=60,
        terminal_service_retention_hours=24,
    )


def _install_lifecycle_fakes(monkeypatch, *, docker_error: Exception | None = None):
    config = _config()
    docker_client = MagicMock()
    docker_client.run = AsyncMock(side_effect=docker_error)
    reconciliation = MagicMock()
    reconciliation.start = AsyncMock()
    reconciliation.stop = AsyncMock()
    teardown = AsyncMock()

    monkeypatch.setattr(
        tactic_main,
        "get_tactic_settings",
        lambda: SimpleNamespace(config=config),
    )
    monkeypatch.setattr(tactic_main, "AsyncDocker", lambda: docker_client)
    monkeypatch.setattr(
        tactic_main,
        "RadarStatusReconciliationService",
        lambda **_kwargs: reconciliation,
    )
    monkeypatch.setattr(
        tactic_main,
        "_teardown_ephemeral_radar_workloads",
        teardown,
    )
    return docker_client, reconciliation, teardown


@pytest.mark.asyncio
async def test_lifespan_releases_resources_when_serving_raises(monkeypatch):
    docker_client, reconciliation, teardown = _install_lifecycle_fakes(monkeypatch)
    app = FastAPI()

    with pytest.raises(RuntimeError, match="request handling failed"):
        async with tactic_main.lifespan(app):
            assert app.state.docker_client is docker_client
            # Request paths reuse the verified client instead of opening their own.
            assert radar_workloads.get_async_docker() is docker_client
            raise RuntimeError("request handling failed")

    reconciliation.start.assert_awaited_once()
    reconciliation.stop.assert_awaited_once()
    assert teardown.await_args_list[0].kwargs["phase"] == "startup"
    assert teardown.await_args_list[1].kwargs["phase"] == "shutdown"
    docker_client.close.assert_called_once()
    assert app.state.docker_client is None
    assert radar_workloads._shared_async_docker is None


@pytest.mark.asyncio
async def test_lifespan_closes_unverified_docker_client(monkeypatch):
    docker_client, reconciliation, teardown = _install_lifecycle_fakes(
        monkeypatch,
        docker_error=ConnectionError("Docker unavailable"),
    )
    app = FastAPI()

    with pytest.raises(ConnectionError, match="Docker unavailable"):
        async with tactic_main.lifespan(app):
            pytest.fail("startup should not complete")

    docker_client.close.assert_called_once()
    reconciliation.start.assert_not_awaited()
    teardown.assert_not_awaited()
    assert app.state.docker_client is None


def _record_lifecycle(monkeypatch):
    """Fake every long-lived service and record start and stop calls in order."""
    calls: list[str] = []
    docker_client, reconciliation, teardown = _install_lifecycle_fakes(monkeypatch)

    def recorder(name):
        return AsyncMock(side_effect=lambda *args, **kwargs: calls.append(name))

    reconciliation.stop = recorder("reconciliation.stop")
    teardown.side_effect = lambda app, phase: calls.append(f"teardown.{phase}")
    docker_client.close.side_effect = lambda: calls.append("docker.close")

    supervisor = SimpleNamespace(
        start=recorder("supervisor.start"), stop=recorder("supervisor.stop")
    )
    ingress = SimpleNamespace(
        start=recorder("ingress.start"), stop=recorder("ingress.stop")
    )
    live = SimpleNamespace(
        start_supervisor=lambda reader: calls.append("live.start"),
        close=recorder("live.close"),
    )
    monkeypatch.setattr(
        tactic_main, "PipelineActivationSupervisor", lambda workloads: supervisor
    )
    monkeypatch.setattr(tactic_main, "SystemIngress", lambda **kwargs: ingress)
    monkeypatch.setattr(tactic_main, "SystemLiveService", lambda *a, **k: live)
    monkeypatch.setattr(tactic_main, "BrokerCheck", lambda *a, **k: object())
    monkeypatch.setattr(tactic_main, "AmbiboxLiveAccess", lambda settings: object())
    monkeypatch.setattr(tactic_main, "get_ambibox_settings", lambda: None)
    monkeypatch.setattr(tactic_main, "get_system_live_settings", lambda: None)
    return calls


@pytest.mark.asyncio
async def test_lifespan_stops_services_in_a_fixed_order(monkeypatch):
    calls = _record_lifecycle(monkeypatch)
    app = FastAPI()

    async with tactic_main.lifespan(app):
        calls.append("serving")

    assert calls == [
        "teardown.startup",
        "supervisor.start",
        "ingress.start",
        "live.start",
        "serving",
        "live.close",
        "supervisor.stop",
        "ingress.stop",
        "reconciliation.stop",
        "teardown.shutdown",
        "docker.close",
    ]
    for attribute in (
        "docker_client",
        "reconciliation_service",
        "pipeline_activation_supervisor",
        "system_ingress",
        "system_live",
    ):
        assert getattr(app.state, attribute) is None


def test_main_keeps_the_service_logging_config(monkeypatch):
    """uvicorn must not replace the YAML handlers with its default config."""
    config = SimpleNamespace(
        service_name="tactic",
        service_version="test",
        docker=SimpleNamespace(base_url="unix:///docker.sock"),
        host="127.0.0.1",
        port=8001,
        log_level="WARNING",
    )
    app = object()
    run = MagicMock()
    for name, value in {
        "start_service": lambda *args, **kwargs: None,
        "get_tactic_settings": lambda: SimpleNamespace(config=config),
        "create_app": lambda: app,
    }.items():
        monkeypatch.setattr(tactic_main, name, value)
    monkeypatch.setattr(tactic_main.uvicorn, "run", run)

    tactic_main.main()

    run.assert_called_once_with(
        app, host="127.0.0.1", port=8001, log_level="warning", log_config=None
    )
