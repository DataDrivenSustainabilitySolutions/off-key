import pytest
from pydantic import ValidationError

from off_key_core.schemas.radar import StaticBaselineConfig, StaticMartingaleConfig
from off_key_mqtt_proxy.config.config import MQTTConfig, MQTTSettings
from off_key_mqtt_radar.config.config import (
    AnomalyDetectionConfig,
    MQTTRadarConfig,
    RadarSettings,
)


def _base_mqtt_config() -> dict:
    return {
        "broker_host": "localhost",
        "broker_port": 1883,
        "use_tls": False,
        "transport": "tcp",
        "client_id_prefix": "proxy",
        "use_auth": True,
        "mqtt_username": "user",
        "mqtt_api_key": "secret-key-123",
        "source_topics": ["charger/+/live-telemetry/#"],
        "topic_regex": (
            r"^charger/(?P<charger_id>[^/]+)/live-telemetry/(?P<telemetry_type>.+)$"
        ),
        "topic_payload_charger_key": "charger_id",
        "topic_payload_type_key": "telemetry_type",
        "enabled": True,
        "reconnect_delay": 5,
        "max_reconnect_attempts": 10,
        "batch_size": 100,
        "batch_timeout": 5.0,
        "subscription_qos": 1,
        "health_check_interval": 35,
        "health_log_reminder_interval": 10,
        "connection_timeout": 30.0,
        "max_message_queue_size": 10000,
        "worker_threads": 4,
    }


def test_mqtt_config_mutable_defaults_are_isolated():
    cfg_one = MQTTConfig(**_base_mqtt_config())
    cfg_two = MQTTConfig(**{**_base_mqtt_config(), "mqtt_api_key": "secret-key-456"})

    cfg_one.bridge_topic_mapping["charger/+/telemetry"] = "radar/+/telemetry"
    assert cfg_two.bridge_topic_mapping == {}


def test_mqtt_radar_config_mutable_defaults_are_isolated():
    cfg_one = MQTTRadarConfig()
    cfg_two = MQTTRadarConfig()

    cfg_one.subscription_topics.append("charger/charger-sim-1/live-telemetry/cosine")
    cfg_one.static_baseline_config.model_params["n_estimators"] = 8

    assert cfg_two.subscription_topics == ["charger/charger-sim-1/live-telemetry/sine"]
    assert cfg_two.static_baseline_config.model_params == {}


@pytest.mark.parametrize(
    "topics, message",
    [
        (["charger/+/live-telemetry/sine"], "concrete MQTT topics"),
        (
            [
                "charger/charger-a/live-telemetry/sine",
                "charger/charger-b/live-telemetry/cosine",
            ],
            "exactly one charger",
        ),
        (
            [
                "charger/charger-a/telemetry/sine",
                "charger/charger-a/live-telemetry/sine",
            ],
            "same sensor path",
        ),
    ],
)
def test_mqtt_radar_config_rejects_ambiguous_static_sensor_assignments(topics, message):
    with pytest.raises(ValidationError, match=message):
        MQTTRadarConfig(subscription_topics=topics)


def test_anomaly_detection_config_rejects_removed_adaptive_fields(monkeypatch):
    from off_key_mqtt_radar import tactic_client

    monkeypatch.setattr(
        tactic_client,
        "validate_model_params",
        lambda _model_type, params=None: params or {},
    )

    with pytest.raises(ValidationError, match="preprocessing_steps"):
        AnomalyDetectionConfig(preprocessing_steps=[])

    with pytest.raises(ValidationError, match="static_baseline"):
        AnomalyDetectionConfig(strategy="adaptive_stream")


def test_radar_settings_parse_static_baseline_strategy(monkeypatch):
    monkeypatch.setenv("RADAR_MONITORING_STRATEGY", "static_baseline")
    monkeypatch.setenv("RADAR_MODEL_TYPE", "pyod_iforest")
    monkeypatch.setenv("RADAR_MODEL_PARAMS", '{"n_estimators": 128}')
    monkeypatch.setenv(
        "RADAR_STATIC_BASELINE_CONFIG",
        """
        {
          "model_type": "pyod_iforest",
          "model_params": {"n_estimators": 128},
          "training_window_size": 240,
          "calibration_window_size": 80,
          "martingale_config": {
            "method": "power",
            "epsilon": 0.5,
            "restarted_ville_threshold": 100
          }
        }
        """,
    )

    cfg = RadarSettings().config

    assert cfg.strategy == "static_baseline"
    assert cfg.model_type == "pyod_iforest"
    assert cfg.model_params["n_estimators"] == 128
    assert cfg.static_baseline_config.training_window_size == 240
    assert cfg.static_baseline_config.calibration_window_size == 80
    assert cfg.static_baseline_config.martingale_config.restarted_ville_threshold == 100


def test_radar_settings_reject_adaptive_strategy(monkeypatch):
    monkeypatch.setenv("RADAR_MONITORING_STRATEGY", "adaptive_stream")

    with pytest.raises(ValidationError, match="static_baseline"):
        RadarSettings()


def test_radar_settings_static_config_is_effective_model_source(monkeypatch):
    monkeypatch.setenv("RADAR_MODEL_TYPE", "pyod_iforest")
    monkeypatch.setenv("RADAR_MODEL_PARAMS", '{"n_estimators": 128}')
    monkeypatch.setenv(
        "RADAR_STATIC_BASELINE_CONFIG",
        """
        {
          "model_type": "pyod_knn",
          "model_params": {"n_neighbors": 7, "contamination": 0.08},
          "training_window_size": 240
        }
        """,
    )

    cfg = RadarSettings().config
    assert cfg.model_type == "pyod_knn"
    assert cfg.model_params == {"n_neighbors": 7, "contamination": 0.08}


def test_radar_settings_reject_non_object_model_params(monkeypatch):
    monkeypatch.setenv("RADAR_MODEL_PARAMS", '["not-a-mapping"]')

    with pytest.raises(ValidationError):
        RadarSettings()


def test_radar_settings_parse_sensor_freshness_seconds(monkeypatch):
    monkeypatch.setenv("RADAR_SENSOR_FRESHNESS_SECONDS", "12.5")
    assert RadarSettings().config.sensor_freshness_seconds == 12.5


def test_static_baseline_legacy_calibration_fraction_sets_window_size():
    config = StaticBaselineConfig(training_window_size=100, calibration_fraction=0.25)
    assert config.calibration_window_size == 25


def test_static_martingale_contract_is_native_and_fixed():
    config = StaticMartingaleConfig()
    assert config.method == "power"
    assert config.epsilon == 0.5
    assert config.restarted_ville_threshold == 100

    with pytest.raises(ValidationError):
        StaticMartingaleConfig(restarted_ville_threshold=50)
    with pytest.raises(ValidationError, match="alpha"):
        StaticMartingaleConfig(alpha=0.01)


def test_static_baseline_rejects_removed_fdr_config():
    with pytest.raises(ValidationError, match="fdr_config"):
        StaticBaselineConfig(fdr_config={})


def test_radar_settings_require_secure_mqtt_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("RADAR_MQTT_USE_TLS", "false")
    monkeypatch.setenv("RADAR_MQTT_USE_AUTH", "false")

    with pytest.raises(ValidationError, match="RADAR_MQTT_USE_TLS"):
        RadarSettings()


def test_radar_settings_allow_insecure_mqtt_in_development(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("RADAR_MQTT_USE_TLS", "false")
    monkeypatch.setenv("RADAR_MQTT_USE_AUTH", "false")
    settings = RadarSettings()
    assert settings.RADAR_MQTT_USE_TLS is False
    assert settings.RADAR_MQTT_USE_AUTH is False


def test_mqtt_config_allows_bridge_auth_fields_when_bridge_disabled():
    MQTTConfig(
        **{
            **_base_mqtt_config(),
            "enable_bridge": False,
            "bridge_use_auth": True,
            "bridge_username": "",
            "bridge_api_key": "",
        }
    )


def test_mqtt_config_requires_bridge_credentials_when_bridge_enabled():
    with pytest.raises(ValidationError, match="Bridge username"):
        MQTTConfig(
            **{
                **_base_mqtt_config(),
                "enable_bridge": True,
                "bridge_broker_host": "emqx-main",
                "bridge_use_auth": True,
                "bridge_username": "",
                "bridge_api_key": "",
            }
        )


def test_mqtt_settings_require_secure_mqtt_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("MQTT_USE_TLS", "false")
    monkeypatch.setenv("MQTT_USE_AUTH", "false")

    with pytest.raises(ValidationError, match="MQTT_USE_TLS"):
        MQTTSettings()


def test_mqtt_settings_allow_insecure_mqtt_in_development(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("MQTT_USE_TLS", "false")
    monkeypatch.setenv("MQTT_USE_AUTH", "false")
    settings = MQTTSettings()
    assert settings.MQTT_USE_TLS is False
    assert settings.MQTT_USE_AUTH is False


def test_mqtt_settings_source_topics_store_normalized_value(monkeypatch):
    monkeypatch.setenv(
        "MQTT_SOURCE_TOPICS",
        (
            " charger/+/live-telemetry/sine ,"
            "charger/+/live-telemetry/sine,"
            " charger/+/live-telemetry/cosine "
        ),
    )

    settings = MQTTSettings()
    assert settings.MQTT_SOURCE_TOPICS == (
        "charger/+/live-telemetry/sine,charger/+/live-telemetry/cosine"
    )
    assert settings.config.source_topics == [
        "charger/+/live-telemetry/sine",
        "charger/+/live-telemetry/cosine",
    ]
