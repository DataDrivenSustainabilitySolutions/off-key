from off_key_tactic_middleware.config import (
    RadarRuntimeSettings,
    RadarWorkloadLifecycle,
    TacticSettings,
)


def test_tactic_settings_expose_radar_workload_image_and_startup_grace():
    settings = TacticSettings(
        TACTIC_RADAR_IMAGE="registry.example/off-key-radar:2026.05.19",
        TACTIC_RADAR_STARTUP_GRACE_SECONDS=7.5,
        TACTIC_TERMINAL_SERVICE_RETENTION_HOURS=12,
    )

    assert settings.config.radar_image == "registry.example/off-key-radar:2026.05.19"
    assert settings.config.radar_startup_grace_seconds == 7.5
    assert settings.config.terminal_service_retention_hours == 12


def test_radar_runtime_settings_carry_no_credential():
    """The pool's children inherit the database and secrets from the replica."""
    settings = RadarRuntimeSettings(ENVIRONMENT="Production")

    assert settings.ENVIRONMENT == "production"
    assert set(RadarRuntimeSettings.model_fields) == {"ENVIRONMENT"}


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


GOLDEN_OVERRIDES = {
    "TACTIC_SERVICE_NAME": "tactic-golden",
    "TACTIC_HOST": "127.0.0.1",
    "TACTIC_PORT": 8100,
    "TACTIC_LOG_LEVEL": "debug",
    "TACTIC_POOL_MEMORY_LIMIT": "1g",
    "TACTIC_POOL_RESTART_MONITORS": False,
    "TACTIC_RADAR_DEFAULT_MQTT_BROKER_HOST": "broker",
    "TACTIC_RADAR_DEFAULT_MQTT_USE_TLS": True,
    "TACTIC_RADAR_DEFAULT_MQTT_USERNAME": "radar",
    "TACTIC_RADAR_DEFAULT_MAX_QUEUE_SIZE": 128,
    "TACTIC_RADAR_DEFAULT_LOG_LEVEL": "warning",
    "TACTIC_RADAR_IMAGE": "registry.example/radar:golden",
    "TACTIC_PIPELINE_MAX_CONCURRENT_PREFLIGHTS": 3,
    "TACTIC_FORECAST_API_URL": "http://forecast:8020",
    "TACTIC_RECONCILIATION_INTERVAL": 30,
    "TACTIC_RADAR_WORKLOAD_LIFECYCLE": "Persistent",
}


def test_config_is_built_field_for_field_from_settings(monkeypatch):
    """Golden mapping of every TACTIC_* setting onto the runtime config."""
    for name in TacticSettings.model_fields:
        monkeypatch.delenv(name, raising=False)
    defaults = TacticSettings().config.model_dump(mode="json")
    golden = TacticSettings(**GOLDEN_OVERRIDES).config.model_dump(mode="json")
    changed = {
        key: value
        for key, value in golden.items()
        if value != defaults[key] and key not in {"pool", "radar_defaults"}
    }
    for section in ("pool", "radar_defaults"):
        changed |= {
            f"{section}.{key}": value
            for key, value in golden[section].items()
            if value != defaults[section][key]
        }
    assert changed == {
        "service_name": "tactic-golden",
        "host": "127.0.0.1",
        "port": 8100,
        "log_level": "DEBUG",
        "radar_image": "registry.example/radar:golden",
        "pipeline_max_concurrent_preflights": 3,
        "forecast_api_url": "http://forecast:8020",
        "reconciliation_interval": 30,
        "radar_workload_lifecycle": "persistent",
        "pool.memory_limit": "1g",
        "pool.restart_monitors": False,
        "radar_defaults.mqtt_broker_host": "broker",
        "radar_defaults.mqtt_use_tls": True,
        "radar_defaults.mqtt_username": "radar",
        "radar_defaults.max_queue_size": 128,
        "radar_defaults.log_level": "WARNING",
    }
    assert defaults["pool"] == {"memory_limit": "512m", "restart_monitors": True}
    assert defaults["radar_workload_lifecycle"] == "ephemeral"
    # No forecast service unless the deployment names one.
    assert defaults["forecast_api_url"] == ""


def test_every_tactic_setting_maps_to_one_config_field():
    """Settings follow <prefix><FIELD>; exceptions are named here with a reason."""
    from off_key_tactic_middleware.config.config import (
        PoolConfig,
        RadarDefaultsConfig,
        TacticConfig,
    )

    derived = {
        # The environment-dependent lifecycle policy.
        "TACTIC_RADAR_WORKLOAD_LIFECYCLE",
        # Read directly by its consumers, outside the runtime config.
        "ENVIRONMENT",
    }
    mapped = (
        {f"TACTIC_{name.upper()}" for name in TacticConfig.model_fields}
        | {f"TACTIC_POOL_{name.upper()}" for name in PoolConfig.model_fields}
        | {
            f"TACTIC_RADAR_DEFAULT_{name.upper()}"
            for name in RadarDefaultsConfig.model_fields
        }
    ) - {
        "TACTIC_POOL",
        "TACTIC_RADAR_DEFAULTS",
        "TACTIC_RADAR_WORKLOAD_LIFECYCLE",
    }
    assert set(TacticSettings.model_fields) == mapped | derived
