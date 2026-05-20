from unittest.mock import AsyncMock

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
