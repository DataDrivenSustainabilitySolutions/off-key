"""
Configuration for MQTT RADAR service
"""

from functools import lru_cache
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Any, Dict, List, Optional, Self
from dotenv import load_dotenv
from pathlib import Path

from off_key_core.config.validation import validate_environment as _validate_environment
from off_key_core.schemas.radar import AdaptiveStreamConfig, StaticBaselineConfig

SENSOR_KEY_STRATEGIES = {"full_hierarchy", "top_level", "leaf"}
MONITORING_STRATEGIES = {"static_baseline", "adaptive_stream"}
# strict_barrier is the only implemented alignment mode. It enforces that all
# sensors in a subscription window must be present before the model is triggered.
# This constant is not a user-selectable enum; it exists so the validator can
# produce a clear error message if a caller passes an unsupported value.
STRICT_ALIGNMENT_MODE = "strict_barrier"


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


def _normalize_alignment_mode(value: str, field_name: str) -> str:
    """Normalize and validate alignment mode values."""
    normalized = value.strip().lower()
    if normalized != STRICT_ALIGNMENT_MODE:
        raise ValueError(f"{field_name} must be: {STRICT_ALIGNMENT_MODE}")
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

    strategy: str = "adaptive_stream"
    model_type: str = "isolation_forest"  # isolation_forest, adaptive_svm, knn
    model_params: Dict[str, Any] = Field(default_factory=dict)
    preprocessing_steps: List[Dict[str, Any]] = Field(default_factory=list)
    static_baseline_config: StaticBaselineConfig = Field(
        default_factory=StaticBaselineConfig
    )
    adaptive_stream_config: AdaptiveStreamConfig = Field(
        default_factory=AdaptiveStreamConfig
    )
    subscription_topics: List[str] = Field(default_factory=list)
    sensor_key_strategy: str = "full_hierarchy"
    sensor_freshness_seconds: float = Field(default=30.0, gt=0.0)
    alignment_mode: str = "strict_barrier"

    thresholds: Dict[str, float] = Field(
        default_factory=lambda: {"medium": 0.6, "high": 0.8, "critical": 0.9}
    )
    heuristic_enabled: bool = True
    heuristic_window_size: int = Field(default=300, ge=3)
    heuristic_min_samples: int = Field(default=30, ge=2)
    heuristic_tail_alpha: float = Field(default=0.005, gt=0.0, lt=1.0)

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

    @field_validator("alignment_mode")
    @classmethod
    def validate_alignment_mode(cls, value: str) -> str:
        """Validate alignment mode used by state cache and persistence semantics."""
        return _normalize_alignment_mode(value, "alignment_mode")

    @model_validator(mode="before")
    @classmethod
    def populate_adaptive_stream_config(cls, data: Any) -> Any:
        """Preserve top-level adaptive model fields when nested config is omitted."""
        if not isinstance(data, dict):
            return data
        if data.get("adaptive_stream_config") is not None:
            return data

        return {
            **data,
            "adaptive_stream_config": {
                "model_type": data.get("model_type", "isolation_forest"),
                "model_params": data.get("model_params", {}),
                "preprocessing_steps": data.get("preprocessing_steps", []),
            },
        }

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

        effective_model_type = self.model_type
        effective_model_params = self.model_params
        effective_preprocessing_steps = self.preprocessing_steps
        if self.strategy == "static_baseline":
            effective_model_type = self.static_baseline_config.model_type
            effective_model_params = self.static_baseline_config.model_params
        else:
            effective_model_type = self.adaptive_stream_config.model_type
            effective_model_params = self.adaptive_stream_config.model_params
            effective_preprocessing_steps = (
                self.adaptive_stream_config.preprocessing_steps
            )

        # Validate model parameters against the registry schema (raises if invalid)
        try:
            validate_model_params(effective_model_type, effective_model_params)
        except ValueError as e:
            raise ValueError(
                f"Invalid model parameters for '{effective_model_type}': {e}"
            ) from e

        # Validate preprocessing steps (raises if invalid)
        try:
            validate_preprocessing_steps(effective_preprocessing_steps)
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
    sensor_freshness_seconds: float = Field(default=30.0, gt=0.0)
    alignment_mode: str = "strict_barrier"

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
    strategy: str = "adaptive_stream"
    model_type: str = "isolation_forest"
    model_params: Dict[str, Any] = Field(default_factory=dict)
    preprocessing_steps: List[Dict[str, Any]] = Field(default_factory=list)
    static_baseline_config: StaticBaselineConfig = Field(
        default_factory=StaticBaselineConfig
    )
    adaptive_stream_config: AdaptiveStreamConfig = Field(
        default_factory=AdaptiveStreamConfig
    )
    thresholds: Dict[str, float] = Field(
        default_factory=lambda: {"medium": 0.6, "high": 0.8, "critical": 0.9}
    )
    heuristic_enabled: bool = True
    heuristic_window_size: int = Field(default=300, ge=3)
    heuristic_min_samples: int = Field(default=30, ge=2)
    heuristic_tail_alpha: float = Field(default=0.005, gt=0.0, lt=1.0)
    batch_size: int = 100
    batch_timeout: float = 1.0
    checkpoint_interval: int = 10000

    @field_validator("sensor_key_strategy")
    @classmethod
    def validate_sensor_key_strategy(cls, value: str) -> str:
        """Validate feature-key strategy used by topic parsing."""
        return _normalize_sensor_key_strategy(value, "sensor_key_strategy")

    @field_validator("strategy")
    @classmethod
    def validate_strategy(cls, value: str) -> str:
        return _normalize_strategy(value, "strategy")

    @field_validator("alignment_mode")
    @classmethod
    def validate_alignment_mode(cls, value: str) -> str:
        """Validate multivariate alignment strategy."""
        return _normalize_alignment_mode(value, "alignment_mode")

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
    RADAR_SUBSCRIPTION_TOPICS: str = "charger/+/live-telemetry/#"  # Comma-separated
    RADAR_SUBSCRIPTION_QOS: int = 0
    RADAR_SENSOR_KEY_STRATEGY: str = "full_hierarchy"
    RADAR_SENSOR_FRESHNESS_SECONDS: float = 30.0
    RADAR_ALIGNMENT_MODE: str = "strict_barrier"

    # Database
    RADAR_DB_WRITE_ENABLED: bool = True
    RADAR_DB_BATCH_SIZE: int = 50
    RADAR_DB_BATCH_TIMEOUT: float = 2.0

    # Anomaly Detection
    RADAR_MONITORING_STRATEGY: str = "adaptive_stream"
    RADAR_MODEL_TYPE: str = "isolation_forest"
    RADAR_MODEL_PARAMS: Dict[str, Any] = Field(default_factory=dict)
    RADAR_PREPROCESSING_STEPS: List[Dict[str, Any]] = Field(default_factory=list)
    RADAR_STATIC_BASELINE_CONFIG: Dict[str, Any] = Field(default_factory=dict)
    RADAR_ADAPTIVE_STREAM_CONFIG: Dict[str, Any] = Field(default_factory=dict)
    RADAR_ANOMALY_THRESHOLD_MEDIUM: float = 0.6
    RADAR_ANOMALY_THRESHOLD_HIGH: float = 0.8
    RADAR_ANOMALY_THRESHOLD_CRITICAL: float = 0.9
    RADAR_HEURISTIC_ENABLED: bool = True
    RADAR_HEURISTIC_WINDOW_SIZE: int = 300
    RADAR_HEURISTIC_MIN_SAMPLES: int = 30
    RADAR_HEURISTIC_TAIL_ALPHA: float = 0.005

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

    @field_validator("RADAR_ALIGNMENT_MODE")
    @classmethod
    def validate_alignment_mode(cls, value: str) -> str:
        """Validate alignment mode from environment."""
        return _normalize_alignment_mode(value, "RADAR_ALIGNMENT_MODE")

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
        topics = [
            topic.strip()
            for topic in self.RADAR_SUBSCRIPTION_TOPICS.split(",")
            if topic.strip()
        ]
        if not topics:
            raise ValueError("At least one subscription topic is required")

        strategy = self.RADAR_MONITORING_STRATEGY
        adaptive_performance_config = {
            "heuristic_enabled": self.RADAR_HEURISTIC_ENABLED,
            "heuristic_window_size": self.RADAR_HEURISTIC_WINDOW_SIZE,
            "heuristic_min_samples": self.RADAR_HEURISTIC_MIN_SAMPLES,
            "heuristic_tail_alpha": self.RADAR_HEURISTIC_TAIL_ALPHA,
            "alignment_mode": self.RADAR_ALIGNMENT_MODE,
            "sensor_key_strategy": self.RADAR_SENSOR_KEY_STRATEGY,
            "sensor_freshness_seconds": self.RADAR_SENSOR_FRESHNESS_SECONDS,
        }
        adaptive_payload = {
            **self.RADAR_ADAPTIVE_STREAM_CONFIG,
            "model_type": self.RADAR_ADAPTIVE_STREAM_CONFIG.get(
                "model_type", self.RADAR_MODEL_TYPE
            ),
            "model_params": self.RADAR_ADAPTIVE_STREAM_CONFIG.get(
                "model_params", self.RADAR_MODEL_PARAMS
            ),
            "preprocessing_steps": self.RADAR_ADAPTIVE_STREAM_CONFIG.get(
                "preprocessing_steps", self.RADAR_PREPROCESSING_STEPS
            ),
        }
        adaptive_payload["performance_config"] = {
            **adaptive_performance_config,
            **self.RADAR_ADAPTIVE_STREAM_CONFIG.get("performance_config", {}),
        }
        adaptive_stream_config = AdaptiveStreamConfig(**adaptive_payload)

        static_baseline_config = StaticBaselineConfig(
            **{
                **self.RADAR_STATIC_BASELINE_CONFIG,
                "model_type": self.RADAR_STATIC_BASELINE_CONFIG.get(
                    "model_type", self.RADAR_MODEL_TYPE
                ),
                "model_params": self.RADAR_STATIC_BASELINE_CONFIG.get(
                    "model_params", self.RADAR_MODEL_PARAMS
                ),
            }
        )
        effective_model_type = self.RADAR_MODEL_TYPE
        effective_model_params = self.RADAR_MODEL_PARAMS
        effective_preprocessing_steps = self.RADAR_PREPROCESSING_STEPS
        effective_sensor_key_strategy = self.RADAR_SENSOR_KEY_STRATEGY
        effective_sensor_freshness_seconds = self.RADAR_SENSOR_FRESHNESS_SECONDS
        effective_alignment_mode = self.RADAR_ALIGNMENT_MODE
        effective_heuristic_enabled = self.RADAR_HEURISTIC_ENABLED
        effective_heuristic_window_size = self.RADAR_HEURISTIC_WINDOW_SIZE
        effective_heuristic_min_samples = self.RADAR_HEURISTIC_MIN_SAMPLES
        effective_heuristic_tail_alpha = self.RADAR_HEURISTIC_TAIL_ALPHA
        if strategy == "static_baseline":
            effective_model_type = static_baseline_config.model_type
            effective_model_params = static_baseline_config.model_params
        else:
            performance_config = adaptive_stream_config.performance_config
            effective_model_type = adaptive_stream_config.model_type
            effective_model_params = adaptive_stream_config.model_params
            effective_preprocessing_steps = adaptive_stream_config.preprocessing_steps
            effective_sensor_key_strategy = performance_config.sensor_key_strategy
            effective_sensor_freshness_seconds = (
                performance_config.sensor_freshness_seconds
            )
            effective_alignment_mode = performance_config.alignment_mode
            effective_heuristic_enabled = performance_config.heuristic_enabled
            effective_heuristic_window_size = performance_config.heuristic_window_size
            effective_heuristic_min_samples = performance_config.heuristic_min_samples
            effective_heuristic_tail_alpha = performance_config.heuristic_tail_alpha

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
            sensor_key_strategy=effective_sensor_key_strategy,
            sensor_freshness_seconds=effective_sensor_freshness_seconds,
            alignment_mode=effective_alignment_mode,
            db_write_enabled=self.RADAR_DB_WRITE_ENABLED,
            db_batch_size=self.RADAR_DB_BATCH_SIZE,
            db_batch_timeout=self.RADAR_DB_BATCH_TIMEOUT,
            health_check_interval=self.RADAR_HEALTH_CHECK_INTERVAL,
            log_level=self.RADAR_LOG_LEVEL,
            rate_limit_per_minute=self.RADAR_RATE_LIMIT_PER_MINUTE,
            memory_limit_mb=self.RADAR_MEMORY_LIMIT_MB,
            strategy=strategy,
            model_type=effective_model_type,
            model_params=effective_model_params,
            static_baseline_config=static_baseline_config,
            adaptive_stream_config=adaptive_stream_config,
            thresholds={
                "medium": self.RADAR_ANOMALY_THRESHOLD_MEDIUM,
                "high": self.RADAR_ANOMALY_THRESHOLD_HIGH,
                "critical": self.RADAR_ANOMALY_THRESHOLD_CRITICAL,
            },
            heuristic_enabled=effective_heuristic_enabled,
            heuristic_window_size=effective_heuristic_window_size,
            heuristic_min_samples=effective_heuristic_min_samples,
            heuristic_tail_alpha=effective_heuristic_tail_alpha,
            batch_size=self.RADAR_BATCH_SIZE,
            batch_timeout=self.RADAR_BATCH_TIMEOUT,
            checkpoint_interval=self.RADAR_CHECKPOINT_INTERVAL,
            preprocessing_steps=effective_preprocessing_steps,
        )


@lru_cache(maxsize=1)
def get_radar_settings() -> RadarSettings:
    """Return cached RADAR settings instance."""
    return RadarSettings()


def clear_radar_settings_cache() -> None:
    """Clear cached RADAR settings (useful for tests and config reloads)."""
    get_radar_settings.cache_clear()
