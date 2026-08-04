"""
Configuration for MQTT RADAR service
"""

from functools import lru_cache
from pathlib import Path
from typing import Any, Self

from dotenv import load_dotenv
from off_key_core.config.validation import validate_environment as _validate_environment
from off_key_core.schemas.radar import (
    AdaptiveStreamConfig,
    StaticBaselineConfig,
    resolve_monitoring_strategy_config,
)
from off_key_core.utils.mqtt_topics import normalize_static_monitoring_topics
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SENSOR_KEY_STRATEGIES = {"full_hierarchy", "top_level", "leaf"}
MONITORING_STRATEGIES = {"static_baseline", "adaptive_stream"}


def _normalize_sensor_key_strategy(value: str, field_name: str) -> str:
    """Normalize and validate sensor key strategy values."""
    normalized = value.strip().lower()
    if normalized not in SENSOR_KEY_STRATEGIES:
        allowed = ", ".join(sorted(SENSOR_KEY_STRATEGIES))
        raise ValueError(f"{field_name} must be one of: {allowed}")
    return normalized


def _normalize_strategy(value: str, field_name: str) -> str:
    """Normalize and validate monitoring strategy values."""
    normalized = value.strip().lower()
    if normalized not in MONITORING_STRATEGIES:
        allowed = ", ".join(sorted(MONITORING_STRATEGIES))
        raise ValueError(f"{field_name} must be one of: {allowed}")
    return normalized


def load_configuration(custom_config_file: str | None = None):
    """Load configuration from environment and optional custom file"""
    # Load custom configuration file if specified
    if custom_config_file:
        config_path = Path(custom_config_file)
        if config_path.exists():
            load_dotenv(config_path, override=True)
            return str(config_path.resolve())

    return None


class AnomalyDetectionConfig(BaseModel):
    """Configuration for anomaly detection models"""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    strategy: str = "static_baseline"
    model_type: str = "pyod_iforest"
    model_params: dict[str, Any] = Field(default_factory=dict)
    static_baseline_config: StaticBaselineConfig = Field(
        default_factory=StaticBaselineConfig
    )
    adaptive_stream_config: AdaptiveStreamConfig | None = None
    subscription_topics: list[str] = Field(default_factory=list)
    sensor_key_strategy: str = "full_hierarchy"
    sensor_freshness_seconds: float = Field(default=30.0, gt=0.0)

    memory_limit_mb: int = 1000
    checkpoint_interval: int = 10000

    # Batch processing
    batch_size: int = 100
    batch_timeout: float = 1.0

    # Memory management
    reset_threshold_mb: int = 500

    @field_validator("sensor_key_strategy")
    @classmethod
    def validate_sensor_key_strategy(cls, value: str) -> str:
        """Validate sensor key strategy for model schema consistency."""
        return _normalize_sensor_key_strategy(value, "sensor_key_strategy")

    @field_validator("strategy")
    @classmethod
    def validate_strategy(cls, value: str) -> str:
        return _normalize_strategy(value, "strategy")


class MQTTRadarConfig(BaseModel):
    """MQTT RADAR service configuration"""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # MQTT Connection
    broker_host: str = "localhost"
    broker_port: int = 1883
    use_tls: bool = False
    client_id_prefix: str = "radar"

    # Optional authentication
    use_auth: bool = False
    username: str = ""
    api_key: str = ""

    # Subscription settings
    subscription_topics: list[str] = Field(
        default_factory=lambda: ["charger/charger-sim-1/live-telemetry/sine"]
    )
    subscription_qos: int = 0
    sensor_key_strategy: str = "full_hierarchy"
    sensor_freshness_seconds: float = Field(default=30.0, gt=0.0)

    # Database settings
    db_write_enabled: bool = True
    db_batch_size: int = 50
    db_batch_timeout: float = 2.0

    # Monitoring
    health_check_interval: float = 30.0
    log_level: str = "INFO"

    # Performance
    worker_threads: int = 4
    max_queue_size: int = 10000

    # Security
    rate_limit_per_minute: int = 1000
    max_feature_count: int = 100
    max_string_length: int = 1000

    # Memory Management
    memory_limit_mb: int = 1000

    # Anomaly Detection
    strategy: str = "static_baseline"
    model_type: str = "pyod_iforest"
    model_params: dict[str, Any] = Field(default_factory=dict)
    static_baseline_config: StaticBaselineConfig = Field(
        default_factory=StaticBaselineConfig
    )
    adaptive_stream_config: AdaptiveStreamConfig | None = None
    batch_size: int = 100
    batch_timeout: float = 1.0
    checkpoint_interval: int = 10000

    @field_validator("sensor_key_strategy")
    @classmethod
    def validate_sensor_key_strategy(cls, value: str) -> str:
        """Validate feature-key strategy used by topic parsing."""
        return _normalize_sensor_key_strategy(value, "sensor_key_strategy")

    @field_validator("subscription_topics")
    @classmethod
    def validate_subscription_topics(cls, value: list[str]) -> list[str]:
        """Keep the runtime feature schema concrete and single-charger."""
        return normalize_static_monitoring_topics(value)

    @field_validator("strategy")
    @classmethod
    def validate_strategy(cls, value: str) -> str:
        return _normalize_strategy(value, "strategy")


class RadarSettings(BaseSettings):
    """Environment-based settings for RADAR service"""

    # Configuration Management
    custom_config_file: str | None = None  # Path to custom config file being watched
    ENVIRONMENT: str = "development"

    # MQTT Configuration
    RADAR_MQTT_BROKER_HOST: str = "localhost"
    RADAR_MQTT_BROKER_PORT: int = 1883
    RADAR_MQTT_USE_TLS: bool = False
    RADAR_MQTT_CLIENT_ID_PREFIX: str = "radar"

    # Authentication
    RADAR_MQTT_USE_AUTH: bool = False
    RADAR_MQTT_USERNAME: str = ""
    RADAR_MQTT_API_KEY: str = ""

    # Topics
    RADAR_SUBSCRIPTION_TOPICS: str = (
        "charger/charger-sim-1/live-telemetry/sine"  # Comma-separated
    )
    RADAR_SUBSCRIPTION_QOS: int = 0
    RADAR_SENSOR_KEY_STRATEGY: str = "full_hierarchy"
    RADAR_SENSOR_FRESHNESS_SECONDS: float = 30.0

    # Database
    RADAR_DB_WRITE_ENABLED: bool = True
    RADAR_DB_BATCH_SIZE: int = 50
    RADAR_DB_BATCH_TIMEOUT: float = 2.0

    # Anomaly Detection
    RADAR_MONITORING_STRATEGY: str = "static_baseline"
    RADAR_MODEL_TYPE: str | None = None
    RADAR_MODEL_PARAMS: dict[str, Any] | None = None
    RADAR_STATIC_BASELINE_CONFIG: dict[str, Any] = Field(default_factory=dict)
    RADAR_ADAPTIVE_STREAM_CONFIG: dict[str, Any] = Field(default_factory=dict)

    # Performance
    RADAR_BATCH_SIZE: int = 100
    RADAR_BATCH_TIMEOUT: float = 1.0
    RADAR_MEMORY_LIMIT_MB: int = 1000
    RADAR_CHECKPOINT_INTERVAL: int = 10000

    # Monitoring
    RADAR_HEALTH_CHECK_INTERVAL: float = 30.0
    RADAR_LOG_LEVEL: str = "INFO"
    RADAR_RATE_LIMIT_PER_MINUTE: int = 1000

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
    )

    @field_validator("RADAR_SUBSCRIPTION_TOPICS")
    @classmethod
    def validate_topics(cls, v: str) -> str:
        """Validate subscription topics format"""
        if not v:
            raise ValueError("At least one subscription topic is required")
        return v

    @field_validator("RADAR_SENSOR_KEY_STRATEGY")
    @classmethod
    def validate_sensor_key_strategy(cls, value: str) -> str:
        """Validate sensor key strategy from environment."""
        return _normalize_sensor_key_strategy(value, "RADAR_SENSOR_KEY_STRATEGY")

    @field_validator("RADAR_MONITORING_STRATEGY")
    @classmethod
    def validate_monitoring_strategy(cls, value: str) -> str:
        return _normalize_strategy(value, "RADAR_MONITORING_STRATEGY")

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        return _validate_environment(value)

    @model_validator(mode="after")
    def validate_mqtt_security_posture(self) -> Self:
        if self.ENVIRONMENT == "production":
            if not self.RADAR_MQTT_USE_TLS:
                raise ValueError(
                    "RADAR_MQTT_USE_TLS must be true when ENVIRONMENT=production"
                )
            if not self.RADAR_MQTT_USE_AUTH:
                raise ValueError(
                    "RADAR_MQTT_USE_AUTH must be true when ENVIRONMENT=production"
                )
        return self

    @property
    def config(self) -> MQTTRadarConfig:
        """Create MQTTRadarConfig from environment settings"""

        # Parse topics
        topics = normalize_static_monitoring_topics(
            [
                topic.strip()
                for topic in self.RADAR_SUBSCRIPTION_TOPICS.split(",")
                if topic.strip()
            ]
        )

        strategy = self.RADAR_MONITORING_STRATEGY
        resolved = resolve_monitoring_strategy_config(
            strategy=strategy,
            model_type=self.RADAR_MODEL_TYPE,
            model_params=self.RADAR_MODEL_PARAMS,
            static_baseline_config=self.RADAR_STATIC_BASELINE_CONFIG or None,
            adaptive_stream_config=self.RADAR_ADAPTIVE_STREAM_CONFIG or None,
        )
        static_baseline_config = (
            resolved.static_baseline_config or StaticBaselineConfig()
        )
        adaptive_stream_config = resolved.adaptive_stream_config

        return MQTTRadarConfig(
            broker_host=self.RADAR_MQTT_BROKER_HOST,
            broker_port=self.RADAR_MQTT_BROKER_PORT,
            use_tls=self.RADAR_MQTT_USE_TLS,
            client_id_prefix=self.RADAR_MQTT_CLIENT_ID_PREFIX,
            use_auth=self.RADAR_MQTT_USE_AUTH,
            username=self.RADAR_MQTT_USERNAME,
            api_key=self.RADAR_MQTT_API_KEY,
            subscription_topics=topics,
            subscription_qos=self.RADAR_SUBSCRIPTION_QOS,
            sensor_key_strategy=self.RADAR_SENSOR_KEY_STRATEGY,
            sensor_freshness_seconds=self.RADAR_SENSOR_FRESHNESS_SECONDS,
            db_write_enabled=self.RADAR_DB_WRITE_ENABLED,
            db_batch_size=self.RADAR_DB_BATCH_SIZE,
            db_batch_timeout=self.RADAR_DB_BATCH_TIMEOUT,
            health_check_interval=self.RADAR_HEALTH_CHECK_INTERVAL,
            log_level=self.RADAR_LOG_LEVEL,
            rate_limit_per_minute=self.RADAR_RATE_LIMIT_PER_MINUTE,
            memory_limit_mb=self.RADAR_MEMORY_LIMIT_MB,
            strategy=strategy,
            model_type=resolved.model_type,
            model_params=resolved.model_params,
            static_baseline_config=static_baseline_config,
            adaptive_stream_config=adaptive_stream_config,
            batch_size=self.RADAR_BATCH_SIZE,
            batch_timeout=self.RADAR_BATCH_TIMEOUT,
            checkpoint_interval=self.RADAR_CHECKPOINT_INTERVAL,
        )


@lru_cache(maxsize=1)
def get_radar_settings() -> RadarSettings:
    """Return cached RADAR settings instance."""
    return RadarSettings()


def clear_radar_settings_cache() -> None:
    """Clear cached RADAR settings (useful for tests and config reloads)."""
    get_radar_settings.cache_clear()
