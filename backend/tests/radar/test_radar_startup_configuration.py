"""RADAR configuration is loaded before construction and is fixed until restart."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from off_key_mqtt_radar import __main__ as entrypoint
from off_key_mqtt_radar.config.config import clear_radar_settings_cache
from off_key_mqtt_radar.config.runtime import clear_radar_runtime_settings_cache
from off_key_mqtt_radar.service import RadarService


@pytest.mark.asyncio
async def test_custom_file_applies_on_startup_and_next_restart(tmp_path, monkeypatch):
    config_file = tmp_path / "radar.env"
    config_file.write_text("RADAR_MQTT_BROKER_HOST=first-broker\n")
    monkeypatch.setenv("RADAR_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("RADAR_MQTT_BROKER_HOST", "environment-broker")
    monkeypatch.setattr(entrypoint, "setup_logging", lambda: None)
    monkeypatch.setattr(entrypoint, "log_startup_logging_configuration", lambda _: None)
    monkeypatch.setattr(entrypoint, "load_env", lambda: None)
    services = []

    def construct_service():
        service = RadarService()
        services.append(service)
        return SimpleNamespace(run=AsyncMock())

    monkeypatch.setattr(entrypoint, "get_radar_service", construct_service)
    try:
        clear_radar_settings_cache()
        clear_radar_runtime_settings_cache()
        await entrypoint.main()
        assert services[0].config.broker_host == "first-broker"
        config_file.write_text("RADAR_MQTT_BROKER_HOST=second-broker\n")
        assert services[0].config.broker_host == "first-broker"
        # A new process begins with fresh settings caches.
        clear_radar_settings_cache()
        clear_radar_runtime_settings_cache()
        await entrypoint.main()
        assert services[1].config.broker_host == "second-broker"
        assert services[0].config.broker_host == "first-broker"
    finally:
        clear_radar_settings_cache()
        clear_radar_runtime_settings_cache()
