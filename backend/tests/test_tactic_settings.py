from off_key_tactic_middleware.config import (
    RadarContainerRuntimeSettings,
    RadarWorkloadLifecycle,
    TacticSettings,
)


def test_split_constraints_parses_csv():
    settings = TacticSettings(
        TACTIC_DOCKER_DEFAULT_CONSTRAINTS=" 'node.role == worker' , rack==1,,"
    )
    assert settings._parse_default_constraints() == ["node.role == worker", "rack==1"]


def test_tactic_settings_expose_radar_workload_image_and_startup_grace():
    settings = TacticSettings(
        TACTIC_RADAR_IMAGE="registry.example/off-key-radar:2026.05.19",
        TACTIC_RADAR_STARTUP_GRACE_SECONDS=7.5,
        TACTIC_TERMINAL_SERVICE_RETENTION_HOURS=12,
    )

    assert settings.config.radar_image == "registry.example/off-key-radar:2026.05.19"
    assert settings.config.radar_startup_grace_seconds == 7.5
    assert settings.config.terminal_service_retention_hours == 12


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


def test_radar_lifecycle_defaults_to_ephemeral_in_development(monkeypatch):
    monkeypatch.delenv("TACTIC_RADAR_WORKLOAD_LIFECYCLE", raising=False)

    settings = TacticSettings(ENVIRONMENT="development")
    assert settings.config.radar_workload_lifecycle == RadarWorkloadLifecycle.EPHEMERAL


def test_radar_lifecycle_defaults_to_persistent_in_production(monkeypatch):
    monkeypatch.delenv("TACTIC_RADAR_WORKLOAD_LIFECYCLE", raising=False)

    settings = TacticSettings(ENVIRONMENT="production")
    assert settings.config.radar_workload_lifecycle == RadarWorkloadLifecycle.PERSISTENT


def test_radar_lifecycle_override_is_respected():
    settings = TacticSettings(
        ENVIRONMENT="production",
        TACTIC_RADAR_WORKLOAD_LIFECYCLE="ephemeral",
    )
    assert settings.config.radar_workload_lifecycle == RadarWorkloadLifecycle.EPHEMERAL
