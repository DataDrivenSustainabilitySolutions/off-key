import pytest
from off_key_core.schemas.radar import StaticBaselineConfig, StaticMartingaleConfig
from off_key_mqtt_proxy.config.config import MQTTConfig, MQTTSettings
from off_key_mqtt_radar.config.config import (
    AnomalyDetectionConfig,
    MQTTRadarConfig,
    RadarSettings,
)
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def _isolated_topic_environment(monkeypatch):
    monkeypatch.delenv("MQTT_SOURCE_TOPICS", raising=False)
    monkeypatch.delenv("RADAR_SUBSCRIPTION_TOPICS", raising=False)


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
        "source_topics": ["device/evCharger/+/#"],
        "topic_regex": (
            r"^device/evCharger/(?P<charger_id>[^/]+)/(?P<telemetry_type>.+)$"
        ),
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

    cfg_one.bridge_topic_mapping["device/evCharger/+/#"] = "radar/+/telemetry"
    assert cfg_two.bridge_topic_mapping == {}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("broker_port", 0),
        ("transport", "udp"),
        ("client_id_prefix", "invalid prefix"),
        ("subscription_qos", 3),
        ("worker_threads", 33),
        ("retry_jitter_magnitude", 0.6),
    ],
)
def test_mqtt_config_rejects_invalid_primitive_constraints(field, value):
    with pytest.raises(ValidationError, match=field):
        MQTTConfig(**{**_base_mqtt_config(), field: value})


def test_mqtt_settings_validate_primitive_constraints(monkeypatch):
    monkeypatch.setenv("MQTT_WORKER_THREADS", "0")

    with pytest.raises(ValidationError, match="MQTT_WORKER_THREADS"):
        MQTTSettings()


def test_mqtt_radar_config_mutable_defaults_are_isolated():
    cfg_one = MQTTRadarConfig()
    cfg_two = MQTTRadarConfig()

    cfg_one.subscription_topics.append("device/evCharger/charger-sim-1/cosine")
    cfg_one.static_baseline_config.model_params["n_estimators"] = 8

    assert cfg_two.subscription_topics == ["device/evCharger/charger-sim-1/sine"]
    assert cfg_two.static_baseline_config.model_params == {}


@pytest.mark.parametrize(
    "topics, message",
    [
        (["device/evCharger/+/sine"], "concrete MQTT topics"),
        (
            [
                "device/evCharger/charger-a/sine",
                "device/evCharger/charger-b/cosine",
            ],
            "exactly one charger",
        ),
    ],
)
def test_mqtt_radar_config_rejects_ambiguous_static_sensor_assignments(topics, message):
    with pytest.raises(ValidationError, match=message):
        MQTTRadarConfig(subscription_topics=topics)


def test_anomaly_detection_config_uses_strategy_specific_adaptive_config():
    with pytest.raises(ValidationError, match="preprocessing_steps"):
        AnomalyDetectionConfig(preprocessing_steps=[])

    config = AnomalyDetectionConfig(
        strategy="adaptive_stream",
        model_type="aberrant_online_isolation_forest",
        adaptive_stream_config={"training_window_size": 1200},
    )
    assert config.strategy == "adaptive_stream"
    assert config.adaptive_stream_config.training_window_size == 1200


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
            "trackers": [{
              "tracker_id": "primary",
              "betting_function": "power",
              "alarm_statistic": "restarted_martingale",
              "epsilon": 0.5,
              "threshold_config": {"mode": "manual", "value": 100}
            }]
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
    threshold = cfg.static_baseline_config.martingale_config.trackers[
        0
    ].threshold_config
    assert threshold.mode == "manual"
    assert threshold.value == 100


def test_radar_settings_parse_adaptive_strategy(monkeypatch):
    monkeypatch.setenv("RADAR_MONITORING_STRATEGY", "adaptive_stream")
    monkeypatch.setenv("RADAR_MODEL_TYPE", "aberrant_online_isolation_forest")
    monkeypatch.setenv(
        "RADAR_ADAPTIVE_STREAM_CONFIG",
        '{"training_window_size": 1200, "calibration_window_size": 360}',
    )

    config = RadarSettings().config
    assert config.strategy == "adaptive_stream"
    assert config.model_type == "aberrant_online_isolation_forest"
    assert config.adaptive_stream_config.threshold_config.quantile == 1.0


def test_radar_settings_reject_conflicting_static_compatibility_mirrors(monkeypatch):
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

    with pytest.raises(ValueError, match="model_type conflicts"):
        _ = RadarSettings().config


def test_radar_settings_reject_non_object_model_params(monkeypatch):
    monkeypatch.setenv("RADAR_MODEL_PARAMS", '["not-a-mapping"]')

    with pytest.raises(ValidationError):
        RadarSettings()


def test_radar_settings_parse_sensor_freshness_seconds(monkeypatch):
    monkeypatch.setenv("RADAR_SENSOR_FRESHNESS_SECONDS", "12.5")
    assert RadarSettings().config.sensor_freshness_seconds == 12.5


def test_static_baseline_rejects_removed_calibration_fraction():
    with pytest.raises(ValidationError, match="calibration_fraction"):
        StaticBaselineConfig(training_window_size=100, calibration_fraction=0.25)


def test_static_martingale_contract_defaults_and_rejects_legacy_payload():
    config = StaticMartingaleConfig()
    primary = config.trackers[0]
    assert primary.betting_function == "power"
    assert primary.alarm_statistic == "restarted_martingale"
    assert primary.epsilon == 0.5
    assert primary.threshold_config.mode == "manual"
    assert primary.threshold_config.value == 100

    with pytest.raises(ValidationError, match="betting_function"):
        StaticMartingaleConfig(
            betting_function="power",
            alarm_statistic="martingale",
            epsilon=0.75,
            restarted_ville_threshold=50,
        )

    ensemble = StaticMartingaleConfig(
        trackers=[
            {
                "tracker_id": "power",
                "betting_function": "power",
                "alarm_statistic": "restarted_martingale",
                "threshold_config": {"mode": "manual", "value": 100},
                "epsilon": 0.5,
            },
            {
                "tracker_id": "mixture-cusum",
                "betting_function": "simple_mixture",
                "alarm_statistic": "cusum",
                "threshold_config": {"mode": "automatic"},
                "n_grid": 64,
                "min_epsilon": 0.02,
            },
            {
                "tracker_id": "jumper-sr",
                "betting_function": "simple_jumper",
                "alarm_statistic": "shiryaev_roberts",
                "threshold_config": {"mode": "manual", "value": 40},
                "jump": 0.05,
            },
        ]
    )
    assert [tracker.tracker_id for tracker in ensemble.trackers] == [
        "power",
        "mixture-cusum",
        "jumper-sr",
    ]

    with pytest.raises(ValidationError, match="unique"):
        StaticMartingaleConfig(
            trackers=[
                {
                    "tracker_id": "duplicate",
                    "betting_function": "power",
                    "epsilon": 0.5,
                },
                {
                    "tracker_id": "duplicate",
                    "betting_function": "simple_jumper",
                    "jump": 0.01,
                },
            ]
        )
    with pytest.raises(ValidationError, match="Ville thresholds"):
        StaticMartingaleConfig(
            trackers=[
                {
                    "tracker_id": "invalid-threshold",
                    "betting_function": "power",
                    "alarm_statistic": "martingale",
                    "threshold_config": {"mode": "manual", "value": 1},
                    "epsilon": 0.5,
                }
            ]
        )
    with pytest.raises(ValidationError, match="method"):
        StaticMartingaleConfig(method="power")
    with pytest.raises(ValidationError, match="alpha"):
        StaticMartingaleConfig(alpha=0.01)


def test_static_martingale_automatic_threshold_constraints():
    with pytest.raises(ValidationError, match="only available"):
        StaticMartingaleConfig(
            trackers=[
                {
                    "tracker_id": "invalid-auto",
                    "betting_function": "power",
                    "alarm_statistic": "martingale",
                    "threshold_config": {"mode": "automatic"},
                }
            ]
        )

    with pytest.raises(ValidationError, match="use at least 199"):
        StaticMartingaleConfig(
            trackers=[
                {
                    "tracker_id": "cusum",
                    "betting_function": "power",
                    "alarm_statistic": "cusum",
                    "threshold_config": {"mode": "automatic"},
                },
                {
                    "tracker_id": "sr",
                    "betting_function": "power",
                    "alarm_statistic": "shiryaev_roberts",
                    "threshold_config": {"mode": "automatic"},
                },
            ],
            automatic_threshold_calibration={
                "false_alarm_probability": 0.01,
                "horizon": 10,
                "simulation_count": 100,
            },
        )

    with pytest.raises(ValidationError, match="computationally large"):
        StaticMartingaleConfig(
            trackers=[
                {
                    "tracker_id": "oversized-mixture",
                    "betting_function": "simple_mixture",
                    "alarm_statistic": "cusum",
                    "threshold_config": {"mode": "automatic"},
                    "n_grid": 10_000,
                }
            ],
            automatic_threshold_calibration={
                "false_alarm_probability": 0.1,
                "horizon": 1_000,
                "simulation_count": 101,
            },
        )


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
            " device/evCharger/+/sine ,"
            "device/evCharger/+/sine,"
            " device/evCharger/+/cosine "
        ),
    )

    settings = MQTTSettings()
    assert settings.MQTT_SOURCE_TOPICS == (
        "device/evCharger/+/sine,device/evCharger/+/cosine"
    )
    assert settings.config.source_topics == [
        "device/evCharger/+/sine",
        "device/evCharger/+/cosine",
    ]


def test_mqtt_settings_default_to_canonical_device_filter():
    settings = MQTTSettings()
    assert settings.MQTT_SOURCE_TOPICS == "device/#"
    assert settings.config.source_topics == ["device/#"]
