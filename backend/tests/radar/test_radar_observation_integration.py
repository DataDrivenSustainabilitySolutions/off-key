"""Real MQTT observations cannot rewind or advance a monitor with invalid time."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from amqtt.client import MQTTClient
from off_key_mqtt_radar import service as service_module
from off_key_mqtt_radar.config.config import MQTTRadarConfig
from off_key_mqtt_radar.config.runtime import clear_radar_runtime_settings_cache
from off_key_mqtt_radar.service import RadarService

from tests.support.form_pipeline import form_radar_config
from tests.support.mqtt import start_mqtt_broker, tiny_adaptive_monitoring, wait_until

pytestmark = pytest.mark.radar_integration


@pytest.mark.asyncio
async def test_real_single_sensor_monitor_rejects_replay_regression_age_and_future(
    monkeypatch,
):
    broker, port = await start_mqtt_broker()
    config = form_radar_config(
        tiny_adaptive_monitoring(),
        ["telemetry/observation/x"],
        MQTTRadarConfig,
        broker_host="127.0.0.1",
        broker_port=port,
        db_write_enabled=False,
        observation_max_age_seconds=2,
        observation_future_tolerance_seconds=1,
        health_check_interval=0.05,
    )
    monkeypatch.setattr(
        service_module, "get_radar_settings", lambda: SimpleNamespace(config=config)
    )
    monkeypatch.setenv("SERVICE_ID", "observation-monitor")
    clear_radar_runtime_settings_cache()
    monitor = RadarService()
    publisher = MQTTClient(client_id="observation-publisher")
    try:
        await monitor.start()
        await publisher.connect(f"mqtt://127.0.0.1:{port}")
        now = datetime.now(UTC)
        for timestamp in (
            now,
            now,
            now - timedelta(milliseconds=100),
            now - timedelta(seconds=10),
            now + timedelta(seconds=10),
        ):
            await publisher.publish(
                "telemetry/observation/x",
                json.dumps(
                    {
                        "value": 1.0,
                        "timestamp": timestamp.isoformat(),
                    }
                ).encode(),
                qos=1,
            )
        await wait_until(lambda: monitor.message_processor.received_message_count == 5)
        assert monitor.detector.primary_service.processed_count == 1
        assert monitor.mqtt_client.coverage.snapshot().dropped_by_reason == {
            "observation_duplicate": 1,
            "observation_regression": 1,
            "observation_too_old": 1,
            "observation_in_future": 1,
        }
        previous_input = monitor.message_processor.activity.snapshot()["last_input_at"]
        assert previous_input is not None
        await publisher.publish(
            "telemetry/observation/x",
            json.dumps(
                {
                    "value": 2.0,
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            ).encode(),
            qos=1,
        )
        await wait_until(lambda: monitor.detector.primary_service.processed_count == 2)
        assert (
            monitor.message_processor.activity.snapshot()["last_input_at"]
            >= previous_input
        )
    finally:
        await monitor.stop()
        await publisher.disconnect()
        await broker.shutdown()
        clear_radar_runtime_settings_cache()
