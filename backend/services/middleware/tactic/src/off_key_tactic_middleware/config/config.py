"""
TACTIC Middleware Configuration

Configuration for the TACTIC
(Timely Anomaly Communication / Task Instance Control) service
including the limits it records for the RADAR pool, RADAR orchestration
settings, and service-specific parameters.
"""

from enum import StrEnum
from functools import cached_property, lru_cache
from typing import Annotated, Any

from off_key_core.config.resource_budget import (
    DEFAULT_RADAR_MAX_ACTIVE_MONITORS,
    DEFAULT_RADAR_MEMORY_MB,
    MEBIBYTE,
    parse_memory_bytes,
    validate_ingress_budget,
)
from off_key_core.config.validation import Environment
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def _log_level(value: str) -> str:
    if value.upper() not in LOG_LEVELS:
        raise ValueError(f"Log level must be one of: {list(LOG_LEVELS)}")
    return value.upper()


LogLevel = Annotated[str, AfterValidator(_log_level)]


class RadarWorkloadLifecycle(StrEnum):
    """Lifecycle behavior for TACTIC-managed RADAR workloads."""

    EPHEMERAL = "ephemeral"
    PERSISTENT = "persistent"


class PoolConfig(BaseModel):
    """What TACTIC records with each workload for the RADAR pool to enforce."""

    # A child of the pool is killed when its resident memory passes this limit.
    memory_limit: str = "512m"
    # A monitor that crashes is started again; a one-off job never is.
    restart_monitors: bool = True

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    @field_validator("memory_limit")
    @classmethod
    def validate_memory_quantity(cls, value: str) -> str:
        parse_memory_bytes(value)
        return value

    @property
    def memory_limit_bytes(self) -> int:
        return parse_memory_bytes(self.memory_limit)


class RadarDefaultsConfig(BaseModel):
    """
    Default configuration values for RADAR services.
    """

    # Default MQTT Settings
    mqtt_broker_host: str = "localhost"
    mqtt_broker_port: int = Field(default=1883, ge=1, le=65535)
    mqtt_use_tls: bool = False
    mqtt_client_id_prefix: str = "radar"
    mqtt_use_auth: bool = False
    mqtt_username: str = ""
    mqtt_qos: int = Field(default=0, ge=0, le=2)

    # Default Performance Settings
    memory_limit_mb: int = Field(default=DEFAULT_RADAR_MEMORY_MB, ge=128, le=16384)
    checkpoint_interval: int = Field(default=10000, ge=100, le=100000)
    max_queue_size: int = Field(default=256, gt=0, le=10000)
    max_payload_bytes: int = Field(default=65536, gt=0, le=1048576)

    # Default Database Settings
    db_write_enabled: bool = True
    db_batch_size: int = Field(default=50, ge=1, le=1000)
    db_batch_timeout: float = Field(default=2.0, ge=0.1, le=3600.0)

    # Default Health Settings
    health_check_interval: float = Field(default=30.0, ge=0.1, le=3600.0)
    log_level: LogLevel = "INFO"
    rate_limit_per_minute: int = Field(default=0, ge=0, le=100000)

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    @model_validator(mode="after")
    def validate_queued_payload_budget(self) -> "RadarDefaultsConfig":
        validate_ingress_budget(
            self.max_queue_size, self.max_payload_bytes, self.memory_limit_mb
        )
        return self


class TacticConfig(BaseModel):
    """
    Complete TACTIC service configuration with business logic validation.
    """

    # Service Information
    service_name: str = "tactic-middleware"
    service_version: str = "0.1.0"

    # API Configuration
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)

    # What the RADAR pool enforces for each workload
    pool: PoolConfig

    # RADAR Defaults
    radar_defaults: RadarDefaultsConfig
    # The image the RADAR pool runs; a workload is pinned to it and only a pool
    # replica of the same image claims it.
    radar_image: str = Field(
        default="ghcr.io/datadrivensustainabilitysolutions/off-key-mqtt-radar:latest",
        min_length=1,
    )
    radar_startup_grace_seconds: float = Field(default=5.0, ge=0.0, le=120.0)
    radar_stop_timeout_seconds: float = Field(default=30.0, ge=1.0, le=300.0)
    radar_max_active_monitors: int = Field(
        default=DEFAULT_RADAR_MAX_ACTIVE_MONITORS,
        ge=1,
        le=10000,
    )
    pipeline_authoring_enabled: bool = True
    pipeline_preflight_timeout_seconds: float = Field(default=90.0, ge=5.0, le=300.0)
    pipeline_heartbeat_timeout_seconds: float = Field(default=120.0, ge=10.0, le=600.0)
    # Any other open activation phase that lasts longer ends as failed.
    pipeline_phase_timeout_seconds: float = Field(default=900.0, ge=60.0, le=7200.0)
    pipeline_max_concurrent_preflights: int = Field(default=2, ge=1, le=32)
    pipeline_max_concurrent_transitions: int = Field(default=8, ge=1, le=64)
    # Where RADAR workers and preflight jobs reach the forecast service that
    # pretrained forecaster steps need; empty in a deployment without one.
    forecast_api_url: str = ""

    # Logging Configuration
    log_level: LogLevel = "INFO"

    # Status Reconciliation Configuration
    reconciliation_enabled: bool = True
    reconciliation_interval: int = Field(default=60, ge=1, le=86400)
    terminal_service_retention_hours: int = Field(default=24, ge=0, le=8760)

    # Managed RADAR workload lifecycle behavior
    radar_workload_lifecycle: RadarWorkloadLifecycle = RadarWorkloadLifecycle.EPHEMERAL

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    @model_validator(mode="after")
    def validate_worker_resource_budget(self) -> "TacticConfig":
        if (
            self.radar_defaults.memory_limit_mb * MEBIBYTE
            >= self.pool.memory_limit_bytes
        ):
            raise ValueError(
                "RADAR internal memory budget must be below its pool memory limit"
            )
        return self


# Defaulted config instances to centralize defaults across settings and runtime
DEFAULT_POOL_CONFIG = PoolConfig()
DEFAULT_RADAR_DEFAULTS = RadarDefaultsConfig()


def _tactic_default(name: str) -> Any:
    return TacticConfig.model_fields[name].default


class TacticSettings(BaseSettings):
    """Environment-based settings for TACTIC service"""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    # Service Configuration
    TACTIC_SERVICE_NAME: str = Field(default=_tactic_default("service_name"))
    TACTIC_SERVICE_VERSION: str = Field(default=_tactic_default("service_version"))
    TACTIC_HOST: str = Field(default=_tactic_default("host"))
    TACTIC_PORT: int = Field(default=_tactic_default("port"))
    TACTIC_LOG_LEVEL: str = Field(default=_tactic_default("log_level"))
    ENVIRONMENT: Environment = Field(default="development")

    # RADAR pool limits
    TACTIC_POOL_MEMORY_LIMIT: str = Field(default=DEFAULT_POOL_CONFIG.memory_limit)
    TACTIC_POOL_RESTART_MONITORS: bool = Field(
        default=DEFAULT_POOL_CONFIG.restart_monitors
    )

    # RADAR Default Configuration
    TACTIC_RADAR_DEFAULT_MQTT_BROKER_HOST: str = Field(
        default=DEFAULT_RADAR_DEFAULTS.mqtt_broker_host
    )
    TACTIC_RADAR_DEFAULT_MQTT_BROKER_PORT: int = Field(
        default=DEFAULT_RADAR_DEFAULTS.mqtt_broker_port
    )
    TACTIC_RADAR_DEFAULT_MQTT_USE_TLS: bool = Field(
        default=DEFAULT_RADAR_DEFAULTS.mqtt_use_tls
    )
    TACTIC_RADAR_DEFAULT_MQTT_CLIENT_ID_PREFIX: str = Field(
        default=DEFAULT_RADAR_DEFAULTS.mqtt_client_id_prefix
    )
    TACTIC_RADAR_DEFAULT_MQTT_USE_AUTH: bool = Field(
        default=DEFAULT_RADAR_DEFAULTS.mqtt_use_auth
    )
    TACTIC_RADAR_DEFAULT_MQTT_USERNAME: str = DEFAULT_RADAR_DEFAULTS.mqtt_username
    TACTIC_RADAR_DEFAULT_MQTT_QOS: int = Field(default=DEFAULT_RADAR_DEFAULTS.mqtt_qos)
    TACTIC_RADAR_DEFAULT_MEMORY_LIMIT_MB: int = Field(
        default=DEFAULT_RADAR_DEFAULTS.memory_limit_mb
    )
    TACTIC_RADAR_DEFAULT_CHECKPOINT_INTERVAL: int = Field(
        default=DEFAULT_RADAR_DEFAULTS.checkpoint_interval
    )
    TACTIC_RADAR_DEFAULT_MAX_QUEUE_SIZE: int = Field(
        default=DEFAULT_RADAR_DEFAULTS.max_queue_size, gt=0, le=10000
    )
    TACTIC_RADAR_DEFAULT_MAX_PAYLOAD_BYTES: int = Field(
        default=DEFAULT_RADAR_DEFAULTS.max_payload_bytes, gt=0, le=1048576
    )
    TACTIC_RADAR_DEFAULT_DB_WRITE_ENABLED: bool = Field(
        default=DEFAULT_RADAR_DEFAULTS.db_write_enabled
    )
    TACTIC_RADAR_DEFAULT_DB_BATCH_SIZE: int = Field(
        default=DEFAULT_RADAR_DEFAULTS.db_batch_size
    )
    TACTIC_RADAR_DEFAULT_DB_BATCH_TIMEOUT: float = Field(
        default=DEFAULT_RADAR_DEFAULTS.db_batch_timeout
    )
    TACTIC_RADAR_DEFAULT_HEALTH_CHECK_INTERVAL: float = Field(
        default=DEFAULT_RADAR_DEFAULTS.health_check_interval
    )
    TACTIC_RADAR_DEFAULT_LOG_LEVEL: str = Field(
        default=DEFAULT_RADAR_DEFAULTS.log_level
    )
    TACTIC_RADAR_DEFAULT_RATE_LIMIT_PER_MINUTE: int = Field(
        default=DEFAULT_RADAR_DEFAULTS.rate_limit_per_minute
    )
    TACTIC_RADAR_IMAGE: str = Field(default=_tactic_default("radar_image"))
    TACTIC_RADAR_STARTUP_GRACE_SECONDS: float = Field(
        default=_tactic_default("radar_startup_grace_seconds")
    )
    TACTIC_RADAR_STOP_TIMEOUT_SECONDS: float = Field(
        default=_tactic_default("radar_stop_timeout_seconds"), ge=1.0, le=300.0
    )
    TACTIC_RADAR_MAX_ACTIVE_MONITORS: int = Field(
        default=DEFAULT_RADAR_MAX_ACTIVE_MONITORS,
        ge=1,
        le=10000,
    )
    TACTIC_PIPELINE_AUTHORING_ENABLED: bool = _tactic_default(
        "pipeline_authoring_enabled"
    )
    TACTIC_PIPELINE_PREFLIGHT_TIMEOUT_SECONDS: float = Field(
        default=_tactic_default("pipeline_preflight_timeout_seconds"), ge=5.0, le=300.0
    )
    TACTIC_PIPELINE_HEARTBEAT_TIMEOUT_SECONDS: float = Field(
        default=_tactic_default("pipeline_heartbeat_timeout_seconds"), ge=10.0, le=600.0
    )
    TACTIC_PIPELINE_PHASE_TIMEOUT_SECONDS: float = Field(
        default=_tactic_default("pipeline_phase_timeout_seconds"), ge=60.0, le=7200.0
    )
    TACTIC_PIPELINE_MAX_CONCURRENT_PREFLIGHTS: int = Field(
        default=_tactic_default("pipeline_max_concurrent_preflights"), ge=1, le=32
    )
    TACTIC_PIPELINE_MAX_CONCURRENT_TRANSITIONS: int = Field(
        default=_tactic_default("pipeline_max_concurrent_transitions"), ge=1, le=64
    )
    TACTIC_FORECAST_API_URL: str = Field(default=_tactic_default("forecast_api_url"))

    # Status Reconciliation Configuration
    TACTIC_RECONCILIATION_ENABLED: bool = Field(
        default=_tactic_default("reconciliation_enabled")
    )
    TACTIC_RECONCILIATION_INTERVAL: int = Field(
        default=_tactic_default("reconciliation_interval")
    )
    TACTIC_TERMINAL_SERVICE_RETENTION_HOURS: int = Field(
        default=_tactic_default("terminal_service_retention_hours")
    )
    TACTIC_RADAR_WORKLOAD_LIFECYCLE: str | None = Field(default=None)

    @staticmethod
    def _normalize_lifecycle_policy(raw_value: str) -> RadarWorkloadLifecycle:
        normalized = raw_value.strip().lower()
        try:
            return RadarWorkloadLifecycle(normalized)
        except ValueError as exc:
            allowed = ", ".join(policy.value for policy in RadarWorkloadLifecycle)
            raise ValueError(
                f"TACTIC_RADAR_WORKLOAD_LIFECYCLE must be one of: {allowed}"
            ) from exc

    def _resolve_radar_workload_lifecycle(self) -> RadarWorkloadLifecycle:
        if self.TACTIC_RADAR_WORKLOAD_LIFECYCLE:
            return self._normalize_lifecycle_policy(
                self.TACTIC_RADAR_WORKLOAD_LIFECYCLE
            )

        if self.ENVIRONMENT == "production":
            return RadarWorkloadLifecycle.PERSISTENT

        return RadarWorkloadLifecycle.EPHEMERAL

    def _section[M: BaseModel](self, model: type[M], prefix: str, **derived: Any) -> M:
        """Build ``model`` from ``<prefix><FIELD>`` settings; ``derived`` fields
        are computed from settings that do not map one to one."""
        values = {
            name: getattr(self, prefix + name.upper())
            for name in model.model_fields
            if name not in derived
        }
        return model(**values, **derived)

    @cached_property
    def config(self) -> TacticConfig:
        """Validated runtime configuration, built once per settings instance."""
        return self._section(
            TacticConfig,
            "TACTIC_",
            pool=self._section(PoolConfig, "TACTIC_POOL_"),
            radar_defaults=self._section(RadarDefaultsConfig, "TACTIC_RADAR_DEFAULT_"),
            radar_workload_lifecycle=self._resolve_radar_workload_lifecycle(),
        )


class RadarRuntimeSettings(BaseSettings):
    """The deployment facts a RADAR workload's environment carries.

    The database and the secrets are the RADAR pool's own: its children inherit
    them, so a workload row never holds a credential.
    """

    model_config = SettingsConfigDict(extra="ignore")

    ENVIRONMENT: Environment = "development"


@lru_cache(maxsize=1)
def get_tactic_settings() -> TacticSettings:
    """Return cached TACTIC settings instance."""
    return TacticSettings()


@lru_cache(maxsize=1)
def get_radar_runtime_settings() -> RadarRuntimeSettings:
    """Return cached settings used to build a RADAR workload's environment."""
    return RadarRuntimeSettings()


def clear_tactic_settings_caches() -> None:
    """Clear cached TACTIC settings for deterministic tests and tooling."""
    get_tactic_settings.cache_clear()
    get_radar_runtime_settings.cache_clear()
