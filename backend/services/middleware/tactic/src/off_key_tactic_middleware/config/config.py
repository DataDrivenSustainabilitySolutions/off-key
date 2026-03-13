"""
TACTIC Middleware Configuration

Configuration for the TACTIC
(Timely Anomaly Communication / Task Instance Control) service
including Docker API configuration,
RADAR orchestration settings, and service-specific parameters.
"""

from enum import Enum
from functools import lru_cache

from off_key_core.config.database import build_postgres_database_url
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, Self

RADAR_SENSOR_KEY_STRATEGIES = {"full_hierarchy", "top_level", "leaf"}


class RadarWorkloadLifecycle(str, Enum):
    """Lifecycle behavior for TACTIC-managed RADAR workloads."""

    EPHEMERAL = "ephemeral"
    PERSISTENT = "persistent"


class DockerConfig(BaseModel):
    """
    Docker API configuration for container orchestration.
    """

    # Docker API Connection
    api_url: str = "http://socket-proxy"
    api_port: int = Field(default=2375, ge=1, le=65535)
    max_concurrent_calls: int = Field(default=5, ge=1, le=100)

    # Container Defaults
    default_network: str = "emqx-network"
    default_restart_policy: str = "on-failure"
    default_restart_max_attempts: int = Field(default=3, ge=0, le=10)

    # Resource Limits
    default_memory_limit: str = "512m"
    default_cpu_limit: str = "0.5"
    default_constraints: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    @property
    def base_url(self) -> str:
        """Get Docker API base URL"""
        return f"{self.api_url}:{self.api_port}"


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
    mqtt_qos: int = Field(default=0, ge=0, le=2)

    # Default Model Settings
    model_type: str = "isolation_forest"
    sensor_key_strategy: str = "full_hierarchy"
    sensor_freshness_seconds: float = Field(default=30.0, gt=0.0)

    # Default Anomaly Thresholds
    anomaly_threshold_medium: float = Field(default=0.6, ge=0.0, le=1.0)
    anomaly_threshold_high: float = Field(default=0.8, ge=0.0, le=1.0)
    anomaly_threshold_critical: float = Field(default=0.9, ge=0.0, le=1.0)

    # Default Performance Settings
    batch_size: int = Field(default=100, ge=1, le=10000)
    batch_timeout: float = Field(default=1.0, ge=0.1, le=3600.0)
    memory_limit_mb: int = Field(default=1000, ge=128, le=16384)
    checkpoint_interval: int = Field(default=10000, ge=100, le=100000)
    heuristic_enabled: bool = True
    heuristic_window_size: int = Field(default=300, ge=3, le=100000)
    heuristic_min_samples: int = Field(default=30, ge=2, le=100000)
    heuristic_zscore_threshold: float = Field(default=3.0, gt=0.0, le=100.0)

    # Default Database Settings
    db_write_enabled: bool = True
    db_batch_size: int = Field(default=50, ge=1, le=1000)
    db_batch_timeout: float = Field(default=2.0, ge=0.1, le=3600.0)

    # Default Health Settings
    health_check_interval: float = Field(default=30.0, ge=0.1, le=3600.0)
    log_level: str = "INFO"
    rate_limit_per_minute: int = Field(default=1000, ge=1, le=100000)

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    @field_validator("model_type")
    @classmethod
    def validate_model_type(cls, v: str) -> str:
        """Validate ML model type"""
        valid_models = ["isolation_forest", "adaptive_svm", "knn"]
        if v not in valid_models:
            raise ValueError(f"Model type must be one of: {valid_models}")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level"""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of: {valid_levels}")
        return v.upper()

    @field_validator("sensor_key_strategy")
    @classmethod
    def validate_sensor_key_strategy(cls, v: str) -> str:
        """Validate feature-key extraction strategy passed to RADAR."""
        normalized = v.strip().lower()
        if normalized not in RADAR_SENSOR_KEY_STRATEGIES:
            allowed = ", ".join(sorted(RADAR_SENSOR_KEY_STRATEGIES))
            raise ValueError(f"sensor_key_strategy must be one of: {allowed}")
        return normalized

    @model_validator(mode="after")
    def validate_threshold_ordering(self) -> Self:
        """Validate that anomaly thresholds are in correct order"""
        if not (
            self.anomaly_threshold_medium
            <= self.anomaly_threshold_high
            <= self.anomaly_threshold_critical
        ):
            raise ValueError(
                "Anomaly thresholds must be ordered: medium <= high <= critical "
                f"(got {self.anomaly_threshold_medium} "
                f"<= {self.anomaly_threshold_high} "
                f"<= {self.anomaly_threshold_critical})"
            )
        if self.heuristic_min_samples > self.heuristic_window_size:
            raise ValueError(
                "heuristic_min_samples must be <= heuristic_window_size "
                f"(got {self.heuristic_min_samples} > {self.heuristic_window_size})"
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

    # Docker Configuration
    docker: DockerConfig

    # RADAR Defaults
    radar_defaults: RadarDefaultsConfig

    # Database Configuration
    database_url: Optional[str] = None

    # Logging Configuration
    log_level: str = "INFO"

    # Status Reconciliation Configuration
    reconciliation_enabled: bool = True
    reconciliation_interval: int = Field(default=60, ge=1, le=86400)

    # Managed RADAR workload lifecycle behavior
    radar_workload_lifecycle: RadarWorkloadLifecycle = RadarWorkloadLifecycle.EPHEMERAL

    # Model Registry Initialization
    model_registry_init_max_retries: int = Field(default=30, ge=1, le=600)
    model_registry_init_retry_interval_seconds: float = Field(
        default=2.0, ge=0.1, le=60.0
    )

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level"""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of: {valid_levels}")
        return v.upper()


# Defaulted config instances to centralize defaults across settings and runtime
DEFAULT_DOCKER_CONFIG = DockerConfig()
DEFAULT_RADAR_DEFAULTS = RadarDefaultsConfig()


class TacticSettings(BaseSettings):
    """Environment-based settings for TACTIC service"""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    # Service Configuration
    TACTIC_SERVICE_NAME: str = Field(default="tactic-middleware")
    TACTIC_SERVICE_VERSION: str = Field(default="0.1.0")
    TACTIC_HOST: str = Field(default="0.0.0.0")
    TACTIC_PORT: int = Field(default=8000)
    TACTIC_LOG_LEVEL: str = Field(default="INFO")
    ENVIRONMENT: str = Field(default="development")

    # Docker API Configuration
    TACTIC_DOCKER_API_URL: str = Field(default=DEFAULT_DOCKER_CONFIG.api_url)
    TACTIC_DOCKER_API_PORT: int = Field(default=DEFAULT_DOCKER_CONFIG.api_port)
    TACTIC_DOCKER_MAX_CONCURRENT_CALLS: int = Field(
        default=DEFAULT_DOCKER_CONFIG.max_concurrent_calls
    )
    TACTIC_DOCKER_DEFAULT_NETWORK: str = Field(
        default=DEFAULT_DOCKER_CONFIG.default_network
    )
    TACTIC_DOCKER_DEFAULT_RESTART_POLICY: str = Field(
        default=DEFAULT_DOCKER_CONFIG.default_restart_policy
    )
    TACTIC_DOCKER_DEFAULT_RESTART_MAX_ATTEMPTS: int = Field(
        default=DEFAULT_DOCKER_CONFIG.default_restart_max_attempts
    )
    TACTIC_DOCKER_DEFAULT_MEMORY_LIMIT: str = Field(
        default=DEFAULT_DOCKER_CONFIG.default_memory_limit
    )
    TACTIC_DOCKER_DEFAULT_CPU_LIMIT: str = Field(
        default=DEFAULT_DOCKER_CONFIG.default_cpu_limit
    )
    TACTIC_DOCKER_DEFAULT_CONSTRAINTS: str = Field(default="node.role == worker")

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
    TACTIC_RADAR_DEFAULT_MQTT_QOS: int = Field(default=DEFAULT_RADAR_DEFAULTS.mqtt_qos)
    TACTIC_RADAR_DEFAULT_MODEL_TYPE: str = Field(
        default=DEFAULT_RADAR_DEFAULTS.model_type
    )
    TACTIC_RADAR_DEFAULT_SENSOR_KEY_STRATEGY: str = Field(
        default=DEFAULT_RADAR_DEFAULTS.sensor_key_strategy
    )
    TACTIC_RADAR_DEFAULT_SENSOR_FRESHNESS_SECONDS: float = Field(
        default=DEFAULT_RADAR_DEFAULTS.sensor_freshness_seconds
    )
    TACTIC_RADAR_DEFAULT_ANOMALY_THRESHOLD_MEDIUM: float = Field(
        default=DEFAULT_RADAR_DEFAULTS.anomaly_threshold_medium
    )
    TACTIC_RADAR_DEFAULT_ANOMALY_THRESHOLD_HIGH: float = Field(
        default=DEFAULT_RADAR_DEFAULTS.anomaly_threshold_high
    )
    TACTIC_RADAR_DEFAULT_ANOMALY_THRESHOLD_CRITICAL: float = Field(
        default=DEFAULT_RADAR_DEFAULTS.anomaly_threshold_critical
    )
    TACTIC_RADAR_DEFAULT_BATCH_SIZE: int = Field(
        default=DEFAULT_RADAR_DEFAULTS.batch_size
    )
    TACTIC_RADAR_DEFAULT_BATCH_TIMEOUT: float = Field(
        default=DEFAULT_RADAR_DEFAULTS.batch_timeout
    )
    TACTIC_RADAR_DEFAULT_MEMORY_LIMIT_MB: int = Field(
        default=DEFAULT_RADAR_DEFAULTS.memory_limit_mb
    )
    TACTIC_RADAR_DEFAULT_CHECKPOINT_INTERVAL: int = Field(
        default=DEFAULT_RADAR_DEFAULTS.checkpoint_interval
    )
    TACTIC_RADAR_DEFAULT_HEURISTIC_ENABLED: bool = Field(
        default=DEFAULT_RADAR_DEFAULTS.heuristic_enabled
    )
    TACTIC_RADAR_DEFAULT_HEURISTIC_WINDOW_SIZE: int = Field(
        default=DEFAULT_RADAR_DEFAULTS.heuristic_window_size
    )
    TACTIC_RADAR_DEFAULT_HEURISTIC_MIN_SAMPLES: int = Field(
        default=DEFAULT_RADAR_DEFAULTS.heuristic_min_samples
    )
    TACTIC_RADAR_DEFAULT_HEURISTIC_ZSCORE_THRESHOLD: float = Field(
        default=DEFAULT_RADAR_DEFAULTS.heuristic_zscore_threshold
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

    # Database Configuration
    TACTIC_DATABASE_URL: Optional[str] = Field(default=None)

    # Status Reconciliation Configuration
    TACTIC_RECONCILIATION_ENABLED: bool = Field(default=True)
    TACTIC_RECONCILIATION_INTERVAL: int = Field(default=60)
    TACTIC_RADAR_WORKLOAD_LIFECYCLE: Optional[str] = Field(default=None)

    # Model Registry Initialization
    TACTIC_MODEL_REGISTRY_INIT_MAX_RETRIES: int = Field(default=30)
    TACTIC_MODEL_REGISTRY_INIT_RETRY_INTERVAL_SECONDS: float = Field(default=2.0)

    @staticmethod
    def _split_constraints(raw_value: str) -> list[str]:
        if not raw_value:
            return []
        values: list[str] = []
        for item in raw_value.split(","):
            cleaned = item.strip()
            if not cleaned:
                continue
            if cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
                cleaned = cleaned[1:-1].strip()
            if cleaned:
                values.append(cleaned)
        return values

    def _parse_default_constraints(self) -> list[str]:
        return self._split_constraints(self.TACTIC_DOCKER_DEFAULT_CONSTRAINTS)

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"development", "test", "staging", "production"}
        if normalized not in allowed:
            allowed_text = ", ".join(sorted(allowed))
            raise ValueError(f"ENVIRONMENT must be one of: {allowed_text}")
        return normalized

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

    @property
    def config(self) -> TacticConfig:
        """
        Create TacticConfig instance from environment settings.

        Returns:
            TacticConfig: Validated TACTIC service configuration
        """
        docker_config = DockerConfig(
            api_url=self.TACTIC_DOCKER_API_URL,
            api_port=self.TACTIC_DOCKER_API_PORT,
            max_concurrent_calls=self.TACTIC_DOCKER_MAX_CONCURRENT_CALLS,
            default_network=self.TACTIC_DOCKER_DEFAULT_NETWORK,
            default_restart_policy=self.TACTIC_DOCKER_DEFAULT_RESTART_POLICY,
            default_restart_max_attempts=self.TACTIC_DOCKER_DEFAULT_RESTART_MAX_ATTEMPTS,
            default_memory_limit=self.TACTIC_DOCKER_DEFAULT_MEMORY_LIMIT,
            default_cpu_limit=self.TACTIC_DOCKER_DEFAULT_CPU_LIMIT,
            default_constraints=self._parse_default_constraints(),
        )

        radar_defaults_config = RadarDefaultsConfig(
            mqtt_broker_host=self.TACTIC_RADAR_DEFAULT_MQTT_BROKER_HOST,
            mqtt_broker_port=self.TACTIC_RADAR_DEFAULT_MQTT_BROKER_PORT,
            mqtt_use_tls=self.TACTIC_RADAR_DEFAULT_MQTT_USE_TLS,
            mqtt_client_id_prefix=self.TACTIC_RADAR_DEFAULT_MQTT_CLIENT_ID_PREFIX,
            mqtt_use_auth=self.TACTIC_RADAR_DEFAULT_MQTT_USE_AUTH,
            mqtt_qos=self.TACTIC_RADAR_DEFAULT_MQTT_QOS,
            model_type=self.TACTIC_RADAR_DEFAULT_MODEL_TYPE,
            sensor_key_strategy=self.TACTIC_RADAR_DEFAULT_SENSOR_KEY_STRATEGY,
            sensor_freshness_seconds=self.TACTIC_RADAR_DEFAULT_SENSOR_FRESHNESS_SECONDS,
            anomaly_threshold_medium=self.TACTIC_RADAR_DEFAULT_ANOMALY_THRESHOLD_MEDIUM,
            anomaly_threshold_high=self.TACTIC_RADAR_DEFAULT_ANOMALY_THRESHOLD_HIGH,
            anomaly_threshold_critical=self.TACTIC_RADAR_DEFAULT_ANOMALY_THRESHOLD_CRITICAL,
            batch_size=self.TACTIC_RADAR_DEFAULT_BATCH_SIZE,
            batch_timeout=self.TACTIC_RADAR_DEFAULT_BATCH_TIMEOUT,
            memory_limit_mb=self.TACTIC_RADAR_DEFAULT_MEMORY_LIMIT_MB,
            checkpoint_interval=self.TACTIC_RADAR_DEFAULT_CHECKPOINT_INTERVAL,
            heuristic_enabled=self.TACTIC_RADAR_DEFAULT_HEURISTIC_ENABLED,
            heuristic_window_size=self.TACTIC_RADAR_DEFAULT_HEURISTIC_WINDOW_SIZE,
            heuristic_min_samples=self.TACTIC_RADAR_DEFAULT_HEURISTIC_MIN_SAMPLES,
            heuristic_zscore_threshold=self.TACTIC_RADAR_DEFAULT_HEURISTIC_ZSCORE_THRESHOLD,
            db_write_enabled=self.TACTIC_RADAR_DEFAULT_DB_WRITE_ENABLED,
            db_batch_size=self.TACTIC_RADAR_DEFAULT_DB_BATCH_SIZE,
            db_batch_timeout=self.TACTIC_RADAR_DEFAULT_DB_BATCH_TIMEOUT,
            health_check_interval=self.TACTIC_RADAR_DEFAULT_HEALTH_CHECK_INTERVAL,
            log_level=self.TACTIC_RADAR_DEFAULT_LOG_LEVEL,
            rate_limit_per_minute=self.TACTIC_RADAR_DEFAULT_RATE_LIMIT_PER_MINUTE,
        )

        return TacticConfig(
            service_name=self.TACTIC_SERVICE_NAME,
            service_version=self.TACTIC_SERVICE_VERSION,
            host=self.TACTIC_HOST,
            port=self.TACTIC_PORT,
            docker=docker_config,
            radar_defaults=radar_defaults_config,
            database_url=self.TACTIC_DATABASE_URL,
            log_level=self.TACTIC_LOG_LEVEL,
            reconciliation_enabled=self.TACTIC_RECONCILIATION_ENABLED,
            reconciliation_interval=self.TACTIC_RECONCILIATION_INTERVAL,
            radar_workload_lifecycle=self._resolve_radar_workload_lifecycle(),
            model_registry_init_max_retries=self.TACTIC_MODEL_REGISTRY_INIT_MAX_RETRIES,
            model_registry_init_retry_interval_seconds=(
                self.TACTIC_MODEL_REGISTRY_INIT_RETRY_INTERVAL_SECONDS
            ),
        )


class RadarContainerRuntimeSettings(BaseSettings):
    """Environment settings used to build RADAR container runtime env vars."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    TACTIC_SERVICE_HOST: str = "tactic-middleware"
    TACTIC_SERVICE_PORT: int = Field(default=8000, ge=1, le=65535)
    TACTIC_MODEL_REGISTRY_CACHE_TTL_SECONDS: float = Field(default=60.0, gt=0)
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: SecretStr = SecretStr("postgres")
    POSTGRES_HOST: str = "timescaledb"
    POSTGRES_PORT: int = Field(default=5432, ge=1, le=65535)
    POSTGRES_DB: str = "postgres"
    ENVIRONMENT: str = "development"

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"development", "test", "staging", "production"}
        if normalized not in allowed:
            allowed_text = ", ".join(sorted(allowed))
            raise ValueError(f"ENVIRONMENT must be one of: {allowed_text}")
        return normalized

    @property
    def radar_database_url(self) -> str:
        return build_postgres_database_url(
            user=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD.get_secret_value(),
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
            database=self.POSTGRES_DB,
            async_driver=True,
        )


@lru_cache(maxsize=1)
def get_tactic_settings() -> TacticSettings:
    """Return cached TACTIC settings instance."""
    return TacticSettings()


# Cache secret-bearing runtime settings once; test helpers clear this cache explicitly.
@lru_cache(maxsize=1)
def get_radar_container_runtime_settings() -> RadarContainerRuntimeSettings:
    """Return cached runtime settings used for RADAR container env assembly."""
    return RadarContainerRuntimeSettings()


def clear_tactic_settings_caches() -> None:
    """Clear cached TACTIC settings for deterministic tests and tooling."""
    get_tactic_settings.cache_clear()
    get_radar_container_runtime_settings.cache_clear()
