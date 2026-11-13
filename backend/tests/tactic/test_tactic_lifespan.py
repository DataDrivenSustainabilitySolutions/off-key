"""The TACTIC worker starts and stops its background resources reliably."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from off_key_tactic_middleware.config import RadarWorkloadLifecycle

tactic_main = import_module("off_key_tactic_middleware.main")


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        radar_workload_lifecycle=RadarWorkloadLifecycle.EPHEMERAL,
        reconciliation_enabled=True,
        reconciliation_interval=60,
        terminal_service_retention_hours=24,
    )


def _install_lifecycle_fakes(monkeypatch):
    config = _config()
    reconciliation = MagicMock()
    reconciliation.start = AsyncMock()
    reconciliation.stop = AsyncMock()
    teardown = AsyncMock()

    monkeypatch.setattr(
        tactic_main,
        "get_tactic_settings",
        lambda: SimpleNamespace(config=config),
    )
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
    return reconciliation, teardown


@pytest.mark.asyncio
async def test_lifespan_releases_resources_when_serving_raises(monkeypatch):
    reconciliation, teardown = _install_lifecycle_fakes(monkeypatch)
    app = FastAPI()

    with pytest.raises(RuntimeError, match="request handling failed"):
        async with tactic_main.lifespan(app):
            assert app.state.ready is True
            raise RuntimeError("request handling failed")

    reconciliation.start.assert_awaited_once()
    reconciliation.stop.assert_awaited_once()
    assert teardown.await_args_list[0].kwargs["phase"] == "startup"
    assert teardown.await_args_list[1].kwargs["phase"] == "shutdown"
    assert app.state.ready is False


@pytest.mark.asyncio
async def test_a_failed_startup_is_never_ready_and_tears_nothing_down_twice(
    monkeypatch,
):
    reconciliation, teardown = _install_lifecycle_fakes(monkeypatch)
    teardown.side_effect = ConnectionError("database unavailable")
    app = FastAPI()

    with pytest.raises(ConnectionError, match="database unavailable"):
        async with tactic_main.lifespan(app):
            pytest.fail("startup should not complete")

    reconciliation.start.assert_not_awaited()
    teardown.assert_awaited_once()
    assert app.state.ready is False


def _record_lifecycle(monkeypatch):
    """Fake every long-lived service and record start and stop calls in order."""
    calls: list[str] = []
    reconciliation, teardown = _install_lifecycle_fakes(monkeypatch)

    def recorder(name):
        return AsyncMock(side_effect=lambda *args, **kwargs: calls.append(name))

    reconciliation.stop = recorder("reconciliation.stop")
    teardown.side_effect = lambda app, phase: calls.append(f"teardown.{phase}")

    supervisor = SimpleNamespace(
        start=recorder("supervisor.start"), stop=recorder("supervisor.stop")
    )
    ingress = SimpleNamespace(
        start=recorder("ingress.start"), stop=recorder("ingress.stop")
    )
    monkeypatch.setattr(
        tactic_main, "PipelineActivationSupervisor", lambda workloads: supervisor
    )
    monkeypatch.setattr(tactic_main, "SystemIngress", lambda **kwargs: ingress)
    monkeypatch.setattr(tactic_main, "BrokerRouteAccess", lambda settings: object())
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
        "serving",
        "supervisor.stop",
        "ingress.stop",
        "reconciliation.stop",
        "teardown.shutdown",
    ]
    assert app.state.ready is False
    for attribute in (
        "reconciliation_service",
        "pipeline_activation_supervisor",
        "system_ingress",
    ):
        assert getattr(app.state, attribute) is None


def test_main_keeps_the_service_logging_config(monkeypatch):
    """uvicorn must not replace the YAML handlers with its default config."""
    config = SimpleNamespace(
        service_name="tactic",
        service_version="test",
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
