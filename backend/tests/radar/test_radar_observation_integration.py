"""Logged readings cannot rewind a monitor."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from off_key_mqtt_radar import service as service_module
from off_key_mqtt_radar.config.config import RadarConfig
from off_key_mqtt_radar.config.runtime import clear_radar_runtime_settings_cache
from off_key_mqtt_radar.service import RadarService

from tests.support.form_pipeline import form_radar_config
from tests.support.mqtt import tiny_adaptive_monitoring, wait_until
from tests.support.telemetry_log import log_reading, log_readings

pytestmark = pytest.mark.radar_integration

TOPIC = "telemetry/observation/x"


@pytest.mark.asyncio
async def test_real_single_sensor_monitor_rejects_a_logged_regression(
    telemetry_log, monkeypatch
):
    config = form_radar_config(
        tiny_adaptive_monitoring(),
        [TOPIC],
        RadarConfig,
        db_write_enabled=False,
        minimum_hold_seconds=2,
        future_tolerance_seconds=1,
        health_check_interval=0.05,
        log_poll_seconds=0.01,
    )
    monkeypatch.setattr(
        service_module, "get_radar_settings", lambda: SimpleNamespace(config=config)
    )
    monkeypatch.setenv("SERVICE_ID", "observation-monitor")
    clear_radar_runtime_settings_cache()
    monitor = RadarService()
    start = datetime.now(UTC)
    try:
        await monitor.start()
        # Logged in this order: the third was received before the second.
        await log_readings(
            telemetry_log,
            [
                (TOPIC, 1.0, start),
                (TOPIC, 1.0, start + timedelta(seconds=1)),
                (TOPIC, 1.0, start + timedelta(milliseconds=500)),
            ],
        )
        await wait_until(lambda: monitor.message_processor.received_message_count == 3)
        assert monitor.detector.primary_service.processed_count == 2
        assert monitor.coverage.snapshot().dropped_by_reason == {
            "observation_regression": 1,
        }
        previous_input = monitor.message_processor.activity.snapshot()["last_input_at"]
        assert previous_input is not None
        await log_reading(telemetry_log, TOPIC, 2.0, start + timedelta(seconds=2))
        await wait_until(lambda: monitor.detector.primary_service.processed_count == 3)
        assert (
            monitor.message_processor.activity.snapshot()["last_input_at"]
            >= previous_input
        )
    finally:
        await monitor.stop()
        clear_radar_runtime_settings_cache()
