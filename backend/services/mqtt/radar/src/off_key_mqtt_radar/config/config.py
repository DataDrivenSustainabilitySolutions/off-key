"""
Configuration for MQTT RADAR service
"""

from functools import lru_cache
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Any, Dict, List, Optional, Self
from dotenv import load_dotenv
from pathlib import Path

SENSOR_KEY_STRATEGIES = {"full_hierarchy", "top_level", "leaf"}


def _normalize_sensor_key_strategy(value: str, field_name: str) -> str:
    """Normalize and validate sensor key strategy values."""
    normalized = value.strip().lower()
    if normalized not in SENSOR_KEY_STRATEGIES:
        allowed = ", ".join(sorted(SENSOR_KEY_STRATEGIES))
        raise ValueError(f"{field_name} must be one of: {allowed}")
    return normalized


def load_configuration(custom_config_file: Optional[str] = None):
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

    model_type: str = "isolation_forest"  # isolation_forest, adaptive_svm, knn
    model_params: Dict[str, Any] = Field(default_factory=dict)
    preprocessing_steps: List[Dict[str, Any]] = Field(default_factory=list)
    subscription_topics: List[str] = Field(default_factory=list)
    sensor_key_strategy: str = "full_hierarchy"

    thresholds: Dict[str, float] = Field(
        default_factory=lambda: {"medium": 0.6, "high": 0.8, "critical": 0.9}
    )
    heuristic_enabled: bool = True
    heuristic_window_size: int = Field(default=300, ge=3)
    heuristic_min_samples: int = Field(default=30, ge=2)
    heuristic_zscore_threshold: float = Field(default=2.0, gt=0.0)

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

    @model_validator(mode="after")
    def validate_model_configuration(self) -> Self:
        """Validate model_params and preprocessing_steps against registry schemas.

        This ensures invalid configurations fail fast at startup rather than
        during model instantiation. Validation is pure - no mutation.
        """
        from ..tactic_client import (
            validate_model_params,
            validate_preprocessing_steps,
        )

        # Validate model parameters against the registry schema (raises if invalid)
        try:
            validate_model_params(self.model_type, self.model_params)
        except ValueError as e:
            raise ValueError(
                f"Invalid model parameters for '{self.model_type}': {e}"
            ) from e

        # Validate preprocessing steps (raises if invalid)
        try:
            validate_preprocessing_steps(self.preprocessing_steps)
        except ValueError as e:
            raise ValueError(f"Invalid preprocessing configuration: {e}") from e

        if self.heuristic_min_samples > self.heuristic_window_size:
            raise ValueError(
                "heuristic_min_samples must be less than or equal to "
                "heuristic_window_size"
            )

        return self

    @classmethod
    def create_normalized(
        cls,
        model_type: str = "isolation_forest",
        model_params: Optional[Dict[str, Any]] = None,
        preprocessing_steps: Optional[List[Dict[str, Any]]] = None,
        **kwargs,
    ) -> "AnomalyDetectionConfig":
        """Factory that normalizes params before creating instance.

        Use this when you want default values applied and parameters
        normalized according to the registry schemas.

        Args:
            model_type: Model type identifier
            model_params: Raw model parameters (will be normalized)
            preprocessing_steps: Raw preprocessing steps (will be normalized)
            **kwargs: Other AnomalyDetectionConfig fields

        Returns:
            AnomalyDetectionConfig with normalized parameters
        """
        from ..tactic_client import (
            validate_model_params,
            validate_preprocessing_steps,
        )

        normalized_params = validate_model_params(model_type, model_params or {})
        normalized_steps = validate_preprocessing_steps(preprocessing_steps or [])

        return cls(
            model_type=model_type,
            model_params=normalized_params,
            preprocessing_steps=normalized_steps,
            **kwargs,
        )


class MQTTRadarConfig(BaseModel):
    """MQTT RADAR service configuration"""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # MQTT Connection
    broker_host: str = "localhost"
    broker_port: int = 1883
    use_tls: bool = False
    client_id_prefix: str = "radar"

    # Authentication (optional)
    use_auth: bool = False
    username: str = ""
    api_key: str = ""

    # Subscription settings
    subscription_topics: List[str] = Field(
        default_factory=lambda: ["charger/+/live-telemetry/#"]
    )
    subscription_qos: int = 0
    sensor_key_strategy: str = "full_hierarchy"

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
    model_type: str = "isolation_forest"
    model_params: Dict[str, Any] = Field(default_factory=dict)
    preprocessing_steps: List[Dict[str, Any]] = Field(default_factory=list)
    thresholds: Dict[str, float] = Field(
        default_factory=lambda: {"medium": 0.6, "high": 0.8, "critical": 0.9}
    )
    heuristic_enabled: bool = True
    heuristic_window_size: int = Field(default=300, ge=3)
    heuristic_min_samples: int = Field(default=30, ge=2)
    heuristic_zscore_threshold: float = Field(default=2.0, gt=0.0)
    batch_size: int = 100
    batch_timeout: float = 1.0
    checkpoint_interval: int = 10000

    @field_validator("sensor_key_strategy")
    @classmethod
    def validate_sensor_key_strategy(cls, value: str) -> str:
        """Validate feature-key strategy used by topic parsing."""
        return _normalize_sensor_key_strategy(value, "sensor_key_strategy")

    @model_validator(mode="after")
    def validate_heuristic_window(self) -> Self:
        """Validate moving-window heuristic configuration."""
        if self.heuristic_min_samples > self.heuristic_window_size:
            raise ValueError(
                "heuristic_min_samples must be less than or equal to "
                "heuristic_window_size"
            )
        return self


class RadarSettings(BaseSettings):
    """Environment-based settings for RADAR service"""

    # Configuration Management
    custom_config_file: Optional[str] = None  # Path to custom config file being watched

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
    RADAR_SUBSCRIPTION_TOPICS: str = "charger/+/live-telemetry/#"  # Comma-separated
    RADAR_SUBSCRIPTION_QOS: int = 0
    RADAR_SENSOR_KEY_STRATEGY: str = "full_hierarchy"

    # Database
    RADAR_DB_WRITE_ENABLED: bool = True
    RADAR_DB_BATCH_SIZE: int = 50
    RADAR_DB_BATCH_TIMEOUT: float = 2.0

    # Anomaly Detection
    RADAR_MODEL_TYPE: str = "isolation_forest"
    RADAR_MODEL_PARAMS: Dict[str, Any] = Field(default_factory=dict)
    RADAR_PREPROCESSING_STEPS: List[Dict[str, Any]] = Field(default_factory=list)
    RADAR_ANOMALY_THRESHOLD_MEDIUM: float = 0.6
    RADAR_ANOMALY_THRESHOLD_HIGH: float = 0.8
    RADAR_ANOMALY_THRESHOLD_CRITICAL: float = 0.9
    RADAR_HEURISTIC_ENABLED: bool = True
    RADAR_HEURISTIC_WINDOW_SIZE: int = 300
    RADAR_HEURISTIC_MIN_SAMPLES: int = 30
    RADAR_HEURISTIC_ZSCORE_THRESHOLD: float = 2.0

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

    @property
    def config(self) -> MQTTRadarConfig:
        """Create MQTTRadarConfig from environment settings"""

        # Parse topics
        topics = [
            topic.strip()
            for topic in self.RADAR_SUBSCRIPTION_TOPICS.split(",")
            if topic.strip()
        ]
        if not topics:
            raise ValueError("At least one subscription topic is required")

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
            db_write_enabled=self.RADAR_DB_WRITE_ENABLED,
            db_batch_size=self.RADAR_DB_BATCH_SIZE,
            db_batch_timeout=self.RADAR_DB_BATCH_TIMEOUT,
            health_check_interval=self.RADAR_HEALTH_CHECK_INTERVAL,
            log_level=self.RADAR_LOG_LEVEL,
            rate_limit_per_minute=self.RADAR_RATE_LIMIT_PER_MINUTE,
            memory_limit_mb=self.RADAR_MEMORY_LIMIT_MB,
            model_type=self.RADAR_MODEL_TYPE,
            model_params=self.RADAR_MODEL_PARAMS,
            thresholds={
                "medium": self.RADAR_ANOMALY_THRESHOLD_MEDIUM,
                "high": self.RADAR_ANOMALY_THRESHOLD_HIGH,
                "critical": self.RADAR_ANOMALY_THRESHOLD_CRITICAL,
            },
            heuristic_enabled=self.RADAR_HEURISTIC_ENABLED,
            heuristic_window_size=self.RADAR_HEURISTIC_WINDOW_SIZE,
            heuristic_min_samples=self.RADAR_HEURISTIC_MIN_SAMPLES,
            heuristic_zscore_threshold=self.RADAR_HEURISTIC_ZSCORE_THRESHOLD,
            batch_size=self.RADAR_BATCH_SIZE,
            batch_timeout=self.RADAR_BATCH_TIMEOUT,
            checkpoint_interval=self.RADAR_CHECKPOINT_INTERVAL,
            preprocessing_steps=self.RADAR_PREPROCESSING_STEPS,
        )


@lru_cache(maxsize=1)
def get_radar_settings() -> RadarSettings:
    """Return cached RADAR settings instance."""
    return RadarSettings()


def clear_radar_settings_cache() -> None:
    """Clear cached RADAR settings (useful for tests and config reloads)."""
    get_radar_settings.cache_clear()
