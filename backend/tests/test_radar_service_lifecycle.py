import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from off_key_mqtt_radar import service as radar_service_module
from off_key_mqtt_radar.service import RadarService


@pytest.mark.asyncio
async def test_radar_service_run_reraises_startup_failure(monkeypatch):
    radar_service = object.__new__(RadarService)
    radar_service.start = AsyncMock(side_effect=RuntimeError("startup failed"))
    radar_service.stop = AsyncMock()
    radar_service.shutdown_event = AsyncMock()

    monkeypatch.setattr(radar_service_module.signal, "signal", lambda *args: None)

    with pytest.raises(RuntimeError, match="startup failed"):
        await RadarService.run(radar_service)

    radar_service.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_radar_service_stop_cleans_up_partially_started_components():
    radar_service = object.__new__(RadarService)
    mqtt_client = SimpleNamespace(stop=AsyncMock())
    database_writer = SimpleNamespace(stop=AsyncMock())

    radar_service.is_running = False
    radar_service.shutdown_event = asyncio.Event()
    radar_service._log_context = {}
    radar_service.config_watcher = None
    radar_service.config_reloader = object()
    radar_service.mqtt_client = mqtt_client
    radar_service.detector = None
    radar_service.database_writer = database_writer
    radar_service.message_processor = None
    radar_service.health_monitor = None
    radar_service.checkpoint_manager = SimpleNamespace(cleanup_lock=MagicMock())

    await RadarService.stop(radar_service)

    mqtt_client.stop.assert_awaited_once()
    database_writer.stop.assert_awaited_once()
    radar_service.checkpoint_manager.cleanup_lock.assert_called_once()
    assert radar_service.mqtt_client is None
    assert radar_service.database_writer is None
