"""RADAR configuration is loaded before construction and is fixed until restart."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from off_key_core.config import bootstrap
from off_key_mqtt_radar import __main__ as entrypoint
from off_key_mqtt_radar.config.config import clear_radar_settings_cache
from off_key_mqtt_radar.config.runtime import clear_radar_runtime_settings_cache
from off_key_mqtt_radar.service import RadarService

from tests.support.form_pipeline import set_pipeline_environment


@pytest.mark.asyncio
async def test_custom_file_applies_on_startup_and_next_restart(tmp_path, monkeypatch):
    config_file = tmp_path / "radar.env"
    config_file.write_text("RADAR_LOG_POLL_SECONDS=1.5\n")
    monkeypatch.setenv("RADAR_CONFIG_FILE", str(config_file))
    monkeypatch.setenv("RADAR_LOG_POLL_SECONDS", "0.5")
    set_pipeline_environment(monkeypatch)
    monkeypatch.setattr(bootstrap, "load_env", lambda: None)
    monkeypatch.setattr(bootstrap, "load_yaml_config", lambda _: None)
    monkeypatch.setattr(bootstrap, "log_startup_logging_configuration", lambda _: None)
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
        assert services[0].config.log_poll_seconds == 1.5
        config_file.write_text("RADAR_LOG_POLL_SECONDS=2.5\n")
        assert services[0].config.log_poll_seconds == 1.5
        # A new process begins with fresh settings caches.
        clear_radar_settings_cache()
        clear_radar_runtime_settings_cache()
        await entrypoint.main()
        assert services[1].config.log_poll_seconds == 2.5
        assert services[0].config.log_poll_seconds == 1.5
    finally:
        clear_radar_settings_cache()
        clear_radar_runtime_settings_cache()
