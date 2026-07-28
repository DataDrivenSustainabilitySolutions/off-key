"""Tests for reliable TACTIC startup and shutdown resource handling."""

from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from off_key_tactic_middleware.config import RadarWorkloadLifecycle

tactic_main = import_module("off_key_tactic_middleware.main")


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        model_registry_init_max_retries=2,
        model_registry_init_retry_interval_seconds=0.01,
        radar_workload_lifecycle=RadarWorkloadLifecycle.EPHEMERAL,
        reconciliation_enabled=True,
        reconciliation_interval=60,
        terminal_service_retention_hours=24,
    )


def _install_lifecycle_fakes(monkeypatch, *, docker_error: Exception | None = None):
    config = _config()
    registry = MagicMock()
    registry.initialize = AsyncMock()
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
    monkeypatch.setattr(tactic_main, "ModelRegistryService", lambda: registry)
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
    return registry, docker_client, reconciliation, teardown


@pytest.mark.asyncio
async def test_lifespan_releases_resources_when_serving_raises(monkeypatch):
    registry, docker_client, reconciliation, teardown = _install_lifecycle_fakes(
        monkeypatch
    )
    app = FastAPI()

    with pytest.raises(RuntimeError, match="request handling failed"):
        async with tactic_main.lifespan(app):
            assert app.state.model_registry_ready is True
            assert app.state.docker_client is docker_client
            raise RuntimeError("request handling failed")

    registry.initialize.assert_awaited_once_with(
        max_retries=2,
        retry_interval_seconds=0.01,
    )
    reconciliation.start.assert_awaited_once()
    reconciliation.stop.assert_awaited_once()
    assert teardown.await_args_list[0].kwargs["phase"] == "startup"
    assert teardown.await_args_list[1].kwargs["phase"] == "shutdown"
    docker_client.close.assert_called_once()
    assert app.state.docker_client is None
    assert app.state.model_registry is None
    assert app.state.model_registry_ready is False


@pytest.mark.asyncio
async def test_lifespan_closes_unverified_docker_client(monkeypatch):
    _, docker_client, reconciliation, teardown = _install_lifecycle_fakes(
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
    assert app.state.model_registry is None
