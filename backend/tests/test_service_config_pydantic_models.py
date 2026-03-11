import pytest
from pydantic import ValidationError

from off_key_mqtt_proxy.config.config import MQTTConfig
from off_key_mqtt_radar.config.config import MQTTRadarConfig, RadarSettings


def test_mqtt_config_mutable_defaults_are_isolated():
    cfg_one = MQTTConfig(
        broker_host="localhost",
        broker_port=1883,
        use_tls=False,
        transport="tcp",
        client_id_prefix="proxy",
        use_auth=True,
        mqtt_username="user",
        mqtt_api_key="secret-key-123",
        source_topics=["charger/+/live-telemetry/#"],
        topic_regex=r"^charger/(?P<charger_id>[^/]+)/live-telemetry/(?P<telemetry_type>.+)$",
        topic_payload_charger_key="charger_id",
        topic_payload_type_key="telemetry_type",
        enabled=True,
        reconnect_delay=5,
        max_reconnect_attempts=10,
        batch_size=100,
        batch_timeout=5.0,
        subscription_qos=1,
        health_check_interval=35,
        health_log_reminder_interval=10,
        connection_timeout=30.0,
        max_message_queue_size=10000,
        worker_threads=4,
    )
    cfg_two = MQTTConfig(
        broker_host="localhost",
        broker_port=1883,
        use_tls=False,
        transport="tcp",
        client_id_prefix="proxy",
        use_auth=True,
        mqtt_username="user",
        mqtt_api_key="secret-key-456",
        source_topics=["charger/+/live-telemetry/#"],
        topic_regex=r"^charger/(?P<charger_id>[^/]+)/live-telemetry/(?P<telemetry_type>.+)$",
        topic_payload_charger_key="charger_id",
        topic_payload_type_key="telemetry_type",
        enabled=True,
        reconnect_delay=5,
        max_reconnect_attempts=10,
        batch_size=100,
        batch_timeout=5.0,
        subscription_qos=1,
        health_check_interval=35,
        health_log_reminder_interval=10,
        connection_timeout=30.0,
        max_message_queue_size=10000,
        worker_threads=4,
    )

    cfg_one.bridge_topic_mapping["charger/+/telemetry"] = "radar/+/telemetry"

    assert cfg_two.bridge_topic_mapping == {}


def test_mqtt_radar_config_mutable_defaults_are_isolated():
    cfg_one = MQTTRadarConfig()
    cfg_two = MQTTRadarConfig()

    cfg_one.thresholds["medium"] = 0.1
    cfg_one.subscription_topics.append("charger/+/extra")

    assert cfg_two.thresholds["medium"] == 0.6
    assert cfg_two.subscription_topics == ["charger/+/live-telemetry/#"]


def test_radar_settings_parse_json_env_fields(monkeypatch):
    monkeypatch.setenv(
        "RADAR_MODEL_PARAMS",
        '{"contamination": 0.02, "n_estimators": 250}',
    )
    monkeypatch.setenv(
        "RADAR_PREPROCESSING_STEPS",
        '[{"type": "moving_average", "params": {"window_size": 5}}]',
    )

    settings = RadarSettings()
    cfg = settings.config

    assert settings.RADAR_MODEL_PARAMS["n_estimators"] == 250
    assert settings.RADAR_PREPROCESSING_STEPS[0]["type"] == "moving_average"
    assert cfg.model_params["contamination"] == 0.02
    assert cfg.preprocessing_steps[0]["params"]["window_size"] == 5


def test_radar_settings_reject_non_object_model_params(monkeypatch):
    monkeypatch.setenv("RADAR_MODEL_PARAMS", '["not-a-mapping"]')

    with pytest.raises(ValidationError):
        RadarSettings()
