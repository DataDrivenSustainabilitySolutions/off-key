import pytest
from pydantic import ValidationError

from off_key_mqtt_proxy.config.config import MQTTConfig, MQTTSettings
from off_key_mqtt_radar.config.config import (
    AnomalyDetectionConfig,
    MQTTRadarConfig,
    RadarSettings,
)
from off_key_core.schemas.radar import FdrConfig, StaticBaselineConfig
from off_key_tactic_middleware.models.schemas import AdaptiveSVMParams, PyODPCAParams


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
    cfg_two = MQTTConfig(
        **{
            **_base_mqtt_config(),
            "mqtt_api_key": "secret-key-456",
        }
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


def test_anomaly_detection_config_builds_adaptive_stream_config_from_top_level_fields(
    monkeypatch,
):
    from off_key_mqtt_radar import tactic_client

    monkeypatch.setattr(
        tactic_client,
        "validate_model_params",
        lambda _model_type, params=None: params or {},
    )
    monkeypatch.setattr(
        tactic_client,
        "validate_preprocessing_steps",
        lambda steps=None: steps or [],
    )

    cfg = AnomalyDetectionConfig(
        model_type="isolation_forest",
        model_params={"num_trees": 50},
        preprocessing_steps=[{"type": "standard_scaler", "params": {}}],
    )

    assert cfg.adaptive_stream_config.model_type == "isolation_forest"
    assert cfg.adaptive_stream_config.model_params == {"num_trees": 50}
    assert cfg.adaptive_stream_config.preprocessing_steps == [
        {"type": "standard_scaler", "params": {}}
    ]


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


def test_radar_settings_adaptive_stream_config_overrides_top_level(monkeypatch):
    monkeypatch.setenv("RADAR_MONITORING_STRATEGY", "adaptive_stream")
    monkeypatch.setenv("RADAR_MODEL_TYPE", "isolation_forest")
    monkeypatch.setenv("RADAR_MODEL_PARAMS", '{"num_trees": 50}')
    monkeypatch.setenv(
        "RADAR_ADAPTIVE_STREAM_CONFIG",
        """
        {
          "model_type": "knn",
          "model_params": {"k": 7, "window_size": 400, "warm_up": 25},
          "preprocessing_steps": [
            {"type": "standard_scaler", "params": {}}
          ],
          "performance_config": {
            "sensor_key_strategy": "leaf",
            "sensor_freshness_seconds": 12.5,
            "heuristic_window_size": 420,
            "heuristic_min_samples": 40
          }
        }
        """,
    )

    cfg = RadarSettings().config

    assert cfg.strategy == "adaptive_stream"
    assert cfg.model_type == "knn"
    assert cfg.model_params == {"k": 7, "window_size": 400, "warm_up": 25}
    assert cfg.preprocessing_steps == [{"type": "standard_scaler", "params": {}}]
    assert cfg.sensor_key_strategy == "leaf"
    assert cfg.sensor_freshness_seconds == 12.5
    assert cfg.heuristic_window_size == 420
    assert cfg.heuristic_min_samples == 40
    assert cfg.adaptive_stream_config.model_type == "knn"
    assert cfg.adaptive_stream_config.performance_config.sensor_key_strategy == "leaf"


def test_radar_settings_reject_non_object_model_params(monkeypatch):
    monkeypatch.setenv("RADAR_MODEL_PARAMS", '["not-a-mapping"]')

    with pytest.raises(ValidationError):
        RadarSettings()


def test_radar_settings_parse_sensor_freshness_seconds(monkeypatch):
    monkeypatch.setenv("RADAR_SENSOR_FRESHNESS_SECONDS", "12.5")
    settings = RadarSettings()

    assert settings.config.sensor_freshness_seconds == 12.5


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
          "calibration_fraction": 0.25,
          "fdr_config": {
            "method": "saffron",
            "alpha": 0.05,
            "wealth": 0.025,
            "lambda_": 0.5
          }
        }
        """,
    )

    cfg = RadarSettings().config

    assert cfg.strategy == "static_baseline"
    assert cfg.model_type == "pyod_iforest"
    assert cfg.model_params["n_estimators"] == 128
    assert cfg.static_baseline_config.training_window_size == 240
    assert cfg.static_baseline_config.fdr_config.lambda_ == 0.5


def test_radar_settings_static_config_is_effective_model_source(monkeypatch):
    monkeypatch.setenv("RADAR_MONITORING_STRATEGY", "static_baseline")
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
    assert cfg.static_baseline_config.model_type == "pyod_knn"


def test_static_baseline_fdr_requires_wealth_below_alpha():
    with pytest.raises(ValidationError, match="wealth must be less than alpha"):
        StaticBaselineConfig(fdr_config=FdrConfig(alpha=0.05, wealth=0.05, lambda_=0.5))


def test_static_baseline_fdr_defaults_to_saffron():
    config = FdrConfig()

    assert config.method == "saffron"
    assert config.alpha == 0.05
    assert config.effective_threshold == 0.05


def test_static_baseline_naive_fdr_uses_cutoff_without_saffron_wealth_rule():
    config = FdrConfig(method="naive", cutoff=0.02, alpha=0.05, wealth=0.05)

    assert config.method == "naive"
    assert config.cutoff == 0.02
    assert config.effective_threshold == 0.02


def test_model_registry_schema_defaults_keep_svm_fields_out_of_pyod_pca():
    pca_defaults = PyODPCAParams().model_dump()
    svm_defaults = AdaptiveSVMParams().model_dump()

    assert "initial_gamma" not in pca_defaults
    assert "buffer_size" not in pca_defaults
    assert "sv_budget" not in pca_defaults
    assert svm_defaults["initial_gamma"] == 1.0
    assert svm_defaults["buffer_size"] == 200
    assert svm_defaults["sv_budget"] == 100


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
