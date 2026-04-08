"""Tests for db-sync API behavior in mqtt_only mode."""

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest

from off_key_db_sync.api import app
from off_key_db_sync.config.config import clear_sync_settings_cache
from off_key_db_sync.service import SyncService


def test_manual_sync_endpoints_return_skipped_in_mqtt_only(monkeypatch):
    monkeypatch.setenv("SYNC_SOURCE_MODE", "mqtt_only")
    clear_sync_settings_cache()

    with TestClient(app) as client:
        chargers = client.post("/sync/chargers")
        cleanup = client.post("/sync/chargers/clean", params={"days_inactive": 7})
        telemetry = client.post("/sync/telemetry", params={"limit": 123})

    assert chargers.status_code == 200
    assert chargers.json()["status"] == "skipped"

    assert cleanup.status_code == 200
    assert cleanup.json()["status"] == "skipped"

    assert telemetry.status_code == 200
    assert telemetry.json()["status"] == "skipped"
    assert telemetry.json()["limit"] == 123

    clear_sync_settings_cache()


def test_sync_status_includes_source_mode(monkeypatch):
    monkeypatch.setenv("SYNC_SOURCE_MODE", "mqtt_only")
    clear_sync_settings_cache()

    with TestClient(app) as client:
        response = client.get("/sync/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_mode"] == "mqtt_only"
    assert payload["running"] is False

    clear_sync_settings_cache()


@pytest.mark.asyncio
async def test_sync_service_start_fails_fast_for_api_source_mode(monkeypatch):
    monkeypatch.setenv("SYNC_SOURCE_MODE", "api")
    clear_sync_settings_cache()

    service = SyncService()
    service._wait_for_database = AsyncMock(return_value=True)
    service._initialize_database = AsyncMock(return_value=True)

    with pytest.raises(RuntimeError, match="SYNC_SOURCE_MODE=api"):
        await service.start()

    assert service.is_running is False
    assert service.initial_sync_complete is False

    clear_sync_settings_cache()
