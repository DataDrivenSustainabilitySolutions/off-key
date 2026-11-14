"""
Configuration for the RADAR monitor runtime
"""

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from off_key_core.config.resource_budget import DEFAULT_RADAR_MEMORY_MB
from off_key_core.config.validation import SECRETS_DIR, Environment
from off_key_core.models.pipelines import derive_monitoring_config
from off_key_core.schemas.pipelines import PipelineExecutionConfig
from off_key_core.schemas.radar import (
    MonitoringConfig,
    PerformanceConfig,
)
from off_key_core.utils.mqtt_topics import (
    normalize_sensor_key_strategy,
    normalize_static_monitoring_topics,
)
from pydantic import ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def load_configuration(custom_config_file: str | None = None):
    """Load configuration from environment and optional custom file"""
    # Load custom configuration file if specified
    if custom_config_file:
        config_path = Path(custom_config_file)
        if config_path.exists():
            load_dotenv(config_path, override=True)
            return str(config_path.resolve())

    return None


# Pipeline workers report at least this often; TACTIC's activation heartbeat
# window must stay above it.
PIPELINE_HEARTBEAT_INTERVAL_CAP = 5.0


class AnomalyDetectionConfig(PerformanceConfig):
    """Configuration for anomaly detection models"""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # Derived from the pipeline, which every monitor runs.
    monitoring: MonitoringConfig
    pipeline: PipelineExecutionConfig
    # A shadow run learns and scores as any other and raises no alarm.
    shadow: bool = False
    subscription_topics: list[str] = Field(default_factory=list)
    memory_limit_mb: int = Field(default=DEFAULT_RADAR_MEMORY_MB, ge=128, le=16384)
    checkpoint_interval: int = 10000

    @model_validator(mode="after")
    def validate_pipeline_resources(self):
        from ..pipelines.plan import ExecutionPlan
        from ..pipelines.resources import estimate_resources

        estimate_resources(ExecutionPlan(self.pipeline), self.memory_limit_mb)
        return self

    @model_validator(mode="before")
    @classmethod
    def normalize_pipeline_monitoring(cls, value):
        if not isinstance(value, dict) or value.get("pipeline") is None:
            return value
        result = dict(value)
        pipeline = PipelineExecutionConfig.model_validate(result["pipeline"])
        derived = derive_monitoring_config(pipeline.definition)
        supplied = result.get("monitoring")
        if supplied is not None:
            supplied = (
                supplied.model_dump(mode="json")
                if hasattr(supplied, "model_dump")
                else supplied
            )
            if supplied != derived.model_dump(mode="json"):
                raise ValueError("Monitoring configuration conflicts with pipeline")
        result["monitoring"] = derived
        expected_topics = sorted(item.accepted_topic for item in pipeline.bindings)
        supplied_topics = result.get("subscription_topics")
        if supplied_topics is not None and sorted(supplied_topics) != expected_topics:
            raise ValueError("Subscription topics conflict with pipeline bindings")
        result["subscription_topics"] = expected_topics
        # Bound graph inspection uses the existing ownership-fenced heartbeat.
        # A single publication serves workspace summaries and selected previews.
        if "health_check_interval" in cls.model_fields:
            result["health_check_interval"] = min(
                result.get("health_check_interval", PIPELINE_HEARTBEAT_INTERVAL_CAP),
                PIPELINE_HEARTBEAT_INTERVAL_CAP,
            )
        return result


class RadarConfig(AnomalyDetectionConfig):
    """One monitor's runtime configuration."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    # The accepted telemetry topics of the pipeline's bindings; each names one
    # stored stream the monitor reads from the telemetry log.
    subscription_topics: list[str] = Field(
        default_factory=lambda: ["telemetry/charger-sim-1/sine"]
    )
    # Database settings
    db_write_enabled: bool = True
    db_batch_size: int = Field(default=50, gt=0)
    db_batch_timeout: float = Field(default=2.0, gt=0)
    # Results waiting for the database; a full queue holds the log reader back.
    max_queue_size: int = Field(default=256, gt=0, le=10000)

    # Telemetry log reads
    log_poll_seconds: float = Field(default=0.5, gt=0, le=30)
    log_batch_size: int = Field(default=500, gt=0, le=10000)

    # Monitoring
    health_check_interval: float = 30.0
    log_level: str = "INFO"

    # Input validation
    max_feature_count: int = 100
    max_string_length: int = 1000

    @field_validator("subscription_topics")
    @classmethod
    def validate_subscription_topics(cls, value: list[str]) -> list[str]:
        """Keep the runtime feature schema concrete and single-charger."""
        return normalize_static_monitoring_topics(value)


class RadarSettings(BaseSettings):
    """Environment-based settings for RADAR service"""

    # Configuration Management
    ENVIRONMENT: Environment = "development"

    # Topics
    RADAR_SUBSCRIPTION_TOPICS: str = "telemetry/charger-sim-1/sine"  # Comma-separated
    RADAR_SENSOR_KEY_STRATEGY: str = "full_hierarchy"
    # MonitorTiming: how long each reading's last value stays usable.
    RADAR_HOLD_INTERVALS: float = 3.0
    RADAR_MINIMUM_HOLD_SECONDS: float = 30.0
    RADAR_FUTURE_TOLERANCE_SECONDS: float = 5.0

    # Database
    RADAR_DB_WRITE_ENABLED: bool = True
    RADAR_DB_BATCH_SIZE: int = 50
    RADAR_DB_BATCH_TIMEOUT: float = 2.0

    # The bound pipeline; TACTIC also passes the strategy settings it derives.
    RADAR_MONITORING_CONFIG: MonitoringConfig | None = None
    RADAR_PIPELINE_CONFIG: PipelineExecutionConfig
    # TACTIC sets it for a shadow run only: every alarm is kept back as muted.
    RADAR_SHADOW: bool = False

    # Telemetry log reads
    RADAR_LOG_POLL_SECONDS: float = Field(default=0.5, gt=0, le=30)
    RADAR_LOG_BATCH_SIZE: int = Field(default=500, gt=0, le=10000)

    # Performance
    RADAR_MAX_QUEUE_SIZE: int = Field(default=256, gt=0, le=10000)
    RADAR_MEMORY_LIMIT_MB: int = Field(
        default=DEFAULT_RADAR_MEMORY_MB, ge=128, le=16384
    )
    RADAR_CHECKPOINT_INTERVAL: int = 10000

    # Monitoring
    RADAR_HEALTH_CHECK_INTERVAL: float = 30.0
    RADAR_LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        secrets_dir=SECRETS_DIR,
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
        return normalize_sensor_key_strategy(value, "RADAR_SENSOR_KEY_STRATEGY")

    @property
    def config(self) -> RadarConfig:
        """The monitor configuration these settings describe."""

        # Parse topics
        topics = normalize_static_monitoring_topics(
            [
                topic.strip()
                for topic in self.RADAR_SUBSCRIPTION_TOPICS.split(",")
                if topic.strip()
            ]
        )

        pipeline = self.RADAR_PIPELINE_CONFIG
        monitoring = derive_monitoring_config(pipeline.definition)
        if self.RADAR_MONITORING_CONFIG not in (None, monitoring):
            raise ValueError("Runtime monitoring conflicts with pipeline")
        expected_topics = sorted(item.accepted_topic for item in pipeline.bindings)
        if (
            "RADAR_SUBSCRIPTION_TOPICS" in self.model_fields_set
            and sorted(topics) != expected_topics
        ):
            raise ValueError("Runtime subscriptions conflict with pipeline bindings")
        topics = expected_topics

        return RadarConfig(
            subscription_topics=topics,
            sensor_key_strategy=self.RADAR_SENSOR_KEY_STRATEGY,
            hold_intervals=self.RADAR_HOLD_INTERVALS,
            minimum_hold_seconds=self.RADAR_MINIMUM_HOLD_SECONDS,
            future_tolerance_seconds=self.RADAR_FUTURE_TOLERANCE_SECONDS,
            db_write_enabled=self.RADAR_DB_WRITE_ENABLED,
            db_batch_size=self.RADAR_DB_BATCH_SIZE,
            db_batch_timeout=self.RADAR_DB_BATCH_TIMEOUT,
            health_check_interval=self.RADAR_HEALTH_CHECK_INTERVAL,
            log_level=self.RADAR_LOG_LEVEL,
            memory_limit_mb=self.RADAR_MEMORY_LIMIT_MB,
            monitoring=monitoring,
            pipeline=pipeline,
            shadow=self.RADAR_SHADOW,
            max_queue_size=self.RADAR_MAX_QUEUE_SIZE,
            log_poll_seconds=self.RADAR_LOG_POLL_SECONDS,
            log_batch_size=self.RADAR_LOG_BATCH_SIZE,
            checkpoint_interval=self.RADAR_CHECKPOINT_INTERVAL,
        )


@lru_cache(maxsize=1)
def get_radar_settings() -> RadarSettings:
    """Return cached RADAR settings instance."""
    return RadarSettings()


def clear_radar_settings_cache() -> None:
    """Clear cached RADAR settings (useful for tests and config reloads)."""
    get_radar_settings.cache_clear()
