import pytest
from off_key_core.schemas.radar import (
    AdaptiveStreamConfig,
    StaticBaselineConfig,
    StaticMartingaleConfig,
)
from off_key_mqtt_proxy.config.config import MQTTConfig, MQTTSettings
from off_key_mqtt_radar.config.config import (
    MQTTRadarConfig,
    RadarSettings,
)
from pydantic import ValidationError

from tests.support.form_pipeline import form_pipeline, form_radar_config

TOPIC = "telemetry/charger-sim-1/sine"


def _run(monkeypatch, monitoring):
    monkeypatch.setenv(
        "RADAR_PIPELINE_CONFIG", form_pipeline(monitoring, [TOPIC]).model_dump_json()
    )


@pytest.fixture(autouse=True)
def _isolated_topic_environment(monkeypatch):
    monkeypatch.delenv("MQTT_SOURCE_TOPICS", raising=False)
    monkeypatch.delenv("RADAR_SUBSCRIPTION_TOPICS", raising=False)
    monkeypatch.delenv("RADAR_MONITORING_CONFIG", raising=False)
    _run(monkeypatch, None)


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
        "topic_regex": (r"^telemetry/(?P<charger_id>[^/]+)/(?P<telemetry_type>.+)$"),
        "enabled": True,
        "batch_size": 100,
        "batch_timeout": 5.0,
        "connection_timeout": 30.0,
        "max_message_queue_size": 10000,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("broker_port", 0),
        ("transport", "udp"),
        ("client_id_prefix", "invalid prefix"),
        ("batch_size", 0),
        ("max_message_queue_size", 99),
        ("retry_jitter_magnitude", 0.6),
    ],
)
def test_mqtt_config_rejects_invalid_primitive_constraints(field, value):
    with pytest.raises(ValidationError, match=field):
        MQTTConfig(**{**_base_mqtt_config(), field: value})


def test_mqtt_settings_validate_primitive_constraints(monkeypatch):
    monkeypatch.setenv("MQTT_BATCH_SIZE", "0")

    with pytest.raises(ValidationError, match="MQTT_BATCH_SIZE"):
        MQTTSettings()


def test_mqtt_radar_config_mutable_defaults_are_isolated():
    cfg_one = form_radar_config(None, [TOPIC], MQTTRadarConfig)
    cfg_two = form_radar_config(None, [TOPIC], MQTTRadarConfig)
    defaults = dict(cfg_two.monitoring.model_params)

    cfg_one.subscription_topics.append("telemetry/charger-sim-1/cosine")
    cfg_one.monitoring.model_params["n_estimators"] = 8

    assert cfg_two.subscription_topics == [TOPIC]
    assert cfg_two.monitoring.model_params == defaults


@pytest.mark.parametrize(
    "topics, message",
    [
        (["telemetry/+/sine"], "concrete MQTT topics"),
        (
            [
                "telemetry/charger-a/sine",
                "telemetry/charger-b/cosine",
            ],
            "exactly one entity",
        ),
    ],
)
def test_mqtt_radar_config_rejects_ambiguous_static_sensor_assignments(topics, message):
    with pytest.raises(ValidationError, match=message):
        form_radar_config(None, topics, MQTTRadarConfig)


def test_anomaly_detection_config_uses_strategy_specific_adaptive_config():
    with pytest.raises(ValidationError, match="preprocessing_steps"):
        form_radar_config(None, ("telemetry/entity/a",), preprocessing_steps=[])

    config = form_radar_config(
        AdaptiveStreamConfig(training_window_size=1200), ("telemetry/entity/a",)
    )
    assert config.monitoring.strategy == "adaptive_stream"
    assert config.monitoring.training_window_size == 1200


def test_radar_settings_parse_static_baseline_strategy(monkeypatch):
    _run(
        monkeypatch,
        StaticBaselineConfig.model_validate(
            {
                "model_type": "pyod_iforest",
                "model_params": {"n_estimators": 128},
                "training_window_size": 240,
                "calibration_window_size": 80,
                "martingale_config": {
                    "trackers": [
                        {
                            "tracker_id": "primary",
                            "betting_function": "power",
                            "alarm_statistic": "restarted_martingale",
                            "epsilon": 0.5,
                            "threshold_config": {"mode": "manual", "value": 100},
                        }
                    ]
                },
            }
        ),
    )

    cfg = RadarSettings().config

    assert cfg.monitoring.strategy == "static_baseline"
    assert cfg.monitoring.model_type == "pyod_iforest"
    assert cfg.monitoring.model_params["n_estimators"] == 128
    assert cfg.monitoring.training_window_size == 240
    assert cfg.monitoring.calibration_window_size == 80
    threshold = cfg.monitoring.martingale_config.trackers[0].threshold_config
    assert threshold.mode == "manual"
    assert threshold.value == 100
    assert cfg.subscription_topics == [TOPIC]


def test_radar_settings_parse_adaptive_strategy(monkeypatch):
    _run(
        monkeypatch,
        AdaptiveStreamConfig(
            model_type="aberrant_online_isolation_forest",
            training_window_size=1200,
            calibration_window_size=360,
        ),
    )

    config = RadarSettings().config
    assert config.monitoring.strategy == "adaptive_stream"
    assert config.monitoring.model_type == "aberrant_online_isolation_forest"
    assert config.monitoring.threshold_config.quantile == 1.0


def test_radar_settings_reject_monitoring_that_conflicts_with_the_pipeline(
    monkeypatch,
):
    monkeypatch.setenv(
        "RADAR_MONITORING_CONFIG",
        StaticBaselineConfig(model_type="pyod_knn").model_dump_json(),
    )

    with pytest.raises(ValueError, match="conflicts with pipeline"):
        _ = RadarSettings().config


def test_radar_settings_require_a_pipeline(monkeypatch):
    monkeypatch.delenv("RADAR_PIPELINE_CONFIG")

    with pytest.raises(ValidationError, match="RADAR_PIPELINE_CONFIG"):
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


def test_radar_settings_read_swarm_mqtt_password(tmp_path, monkeypatch):
    monkeypatch.delenv("RADAR_MQTT_API_KEY", raising=False)
    (tmp_path / "RADAR_MQTT_API_KEY").write_text("radar-password-123456")
    settings = RadarSettings(
        ENVIRONMENT="production",
        RADAR_MQTT_USE_TLS=True,
        RADAR_MQTT_USE_AUTH=True,
        RADAR_MQTT_USERNAME="offkey-radar",
        RADAR_MQTT_CA_FILE="/run/secrets/EMQX_CA_CERT",
        _secrets_dir=tmp_path,
    )
    assert settings.config.api_key == "radar-password-123456"
    assert settings.config.ca_file == "/run/secrets/EMQX_CA_CERT"


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


def test_mqtt_settings_read_swarm_mqtt_password(tmp_path, monkeypatch):
    monkeypatch.delenv("MQTT_APIKEY", raising=False)
    (tmp_path / "MQTT_APIKEY").write_text("proxy-password-123456")
    settings = MQTTSettings(
        ENVIRONMENT="production",
        MQTT_USE_TLS=True,
        MQTT_USE_AUTH=True,
        MQTT_USERNAME="offkey-proxy",
        MQTT_CA_FILE="/run/secrets/EMQX_CA_CERT",
        _secrets_dir=tmp_path,
    )
    assert settings.config.mqtt_api_key == "proxy-password-123456"
    assert settings.config.ca_file == "/run/secrets/EMQX_CA_CERT"
