import pytest

from off_key_tactic_middleware.config import (
    RadarContainerRuntimeSettings,
    RadarWorkloadLifecycle,
    TacticSettings,
    RadarDefaultsConfig,
)


def test_split_constraints_parses_csv():
    settings = TacticSettings(
        TACTIC_DOCKER_DEFAULT_CONSTRAINTS=" 'node.role == worker' , rack==1,,"
    )
    assert settings._parse_default_constraints() == ["node.role == worker", "rack==1"]


def test_threshold_ordering_validation():
    with pytest.raises(ValueError):
        RadarDefaultsConfig(
            anomaly_threshold_medium=0.9,
            anomaly_threshold_high=0.5,
            anomaly_threshold_critical=0.7,
        )


def test_sensor_key_strategy_validation():
    config = RadarDefaultsConfig(sensor_key_strategy="TOP_LEVEL")
    assert config.sensor_key_strategy == "top_level"

    with pytest.raises(ValueError):
        RadarDefaultsConfig(sensor_key_strategy="invalid")


def test_heuristic_window_validation():
    with pytest.raises(ValueError, match="heuristic_min_samples must be <="):
        RadarDefaultsConfig(heuristic_window_size=20, heuristic_min_samples=25)


def test_tactic_settings_expose_heuristic_and_freshness_defaults():
    settings = TacticSettings(
        TACTIC_RADAR_DEFAULT_HEURISTIC_WINDOW_SIZE=420,
        TACTIC_RADAR_DEFAULT_HEURISTIC_MIN_SAMPLES=40,
        TACTIC_RADAR_DEFAULT_HEURISTIC_ZSCORE_THRESHOLD=4.1,
        TACTIC_RADAR_DEFAULT_SENSOR_FRESHNESS_SECONDS=18.0,
    )
    defaults = settings.config.radar_defaults

    assert defaults.heuristic_window_size == 420
    assert defaults.heuristic_min_samples == 40
    assert defaults.heuristic_zscore_threshold == 4.1
    assert defaults.sensor_freshness_seconds == 18.0


def test_radar_container_runtime_settings_build_encoded_database_url():
    settings = RadarContainerRuntimeSettings(
        POSTGRES_USER="db@user",
        POSTGRES_PASSWORD="p@ss",
        POSTGRES_HOST="db-host",
        POSTGRES_PORT=5432,
        POSTGRES_DB="radar",
        ENVIRONMENT="Production",
    )

    assert settings.ENVIRONMENT == "production"
    assert (
        settings.radar_database_url
        == "postgresql+asyncpg://db%40user:p%40ss@db-host:5432/radar"
    )


def test_radar_lifecycle_defaults_to_ephemeral_in_development():
    settings = TacticSettings(ENVIRONMENT="development")
    assert settings.config.radar_workload_lifecycle == RadarWorkloadLifecycle.EPHEMERAL


def test_radar_lifecycle_defaults_to_persistent_in_production():
    settings = TacticSettings(ENVIRONMENT="production")
    assert settings.config.radar_workload_lifecycle == RadarWorkloadLifecycle.PERSISTENT


def test_radar_lifecycle_override_is_respected():
    settings = TacticSettings(
        ENVIRONMENT="production",
        TACTIC_RADAR_WORKLOAD_LIFECYCLE="ephemeral",
    )
    assert settings.config.radar_workload_lifecycle == RadarWorkloadLifecycle.EPHEMERAL
