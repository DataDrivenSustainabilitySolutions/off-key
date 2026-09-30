"""
MQTT proxy configuration.
"""

import random
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from off_key_core.config.validation import validate_environment as _validate_environment
from off_key_core.utils.mqtt_topics import (
    DEFAULT_TOPIC_REGEX,
    TopicMetadataExtractor,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Transport = Literal["tcp", "websockets"]


def _validate_auth_credentials(
    *,
    enabled: bool,
    username: str,
    api_key: str,
    label: str,
) -> None:
    """Validate credentials only when their authentication path is active."""
    if not enabled:
        return
    if not username.strip():
        raise ValueError(f"{label} username is required when auth is enabled")
    if len(api_key.strip()) < 10:
        raise ValueError(
            f"{label} API key must be at least 10 characters when auth is enabled"
        )


class MQTTConfig(BaseModel):
    """
    Validated runtime configuration for MQTT proxy.
    """

    # MQTT Broker Configuration
    broker_host: str = Field(min_length=1)
    broker_port: int = Field(ge=1, le=65535)
    use_tls: bool
    ca_file: str | None = None
    transport: Transport = "tcp"
    client_id_prefix: str = Field(
        min_length=1,
        max_length=50,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    use_auth: bool
    mqtt_username: str
    mqtt_api_key: str

    topic_regex: str = DEFAULT_TOPIC_REGEX

    # Service Configuration
    enabled: bool
    reconnect_delay: int = Field(ge=1, le=300)
    max_reconnect_attempts: int = Field(ge=1, le=100)

    # Message Processing
    batch_size: int = Field(ge=1, le=10_000)
    batch_timeout: float = Field(ge=0.1, le=300.0)
    subscription_qos: Literal[0, 1, 2]

    # Health Monitoring
    health_check_interval: int = Field(ge=5, le=3_600)
    health_log_reminder_interval: int = Field(ge=1, le=1_000)
    connection_timeout: float = Field(ge=1.0, le=120.0)

    # Performance Tuning
    max_message_queue_size: int = Field(ge=100, le=100_000)
    worker_threads: int = Field(ge=1, le=32)

    # Retry Configuration
    retry_base_delay: float = Field(default=0.1, ge=0.01, le=10.0)
    retry_max_delay: float = Field(default=5.0, ge=0.1, le=60.0)
    retry_exponential_base: float = Field(default=2.0, ge=1.1, le=10.0)
    retry_jitter_enabled: bool = True
    retry_jitter_magnitude: float = Field(default=0.2, ge=0.0, le=0.5)

    # Background Task Intervals
    metrics_interval: float = Field(default=300.0, ge=30.0, le=7_200.0)
    health_monitor_interval: float = Field(default=30.0, ge=5.0, le=300.0)

    # Shutdown Configuration
    shutdown_timeout: float = Field(default=10.0, ge=1.0, le=60.0)
    graceful_shutdown_timeout: float = Field(default=30.0, ge=5.0, le=300.0)

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    @model_validator(mode="after")
    def validate_timing_relationships(self) -> Self:
        """Validate relationships between otherwise valid timing values."""
        min_health_margin_seconds = 5
        if self.health_check_interval < (
            self.connection_timeout + min_health_margin_seconds
        ):
            raise ValueError(
                f"Health check interval ({self.health_check_interval}s) must be > "
                f"{min_health_margin_seconds}s than connection timeout "
                f"({self.connection_timeout}s)."
            )

        if self.batch_timeout >= self.connection_timeout:
            raise ValueError(
                f"Batch timeout ({self.batch_timeout}s) must be less than connection "
                f"timeout ({self.connection_timeout}s)."
            )

        if self.retry_max_delay <= self.retry_base_delay:
            raise ValueError(
                f"Retry max delay ({self.retry_max_delay}s) must be greater than "
                f"retry base delay ({self.retry_base_delay}s)."
            )

        return self

    @model_validator(mode="after")
    def validate_runtime_dependencies(self) -> Self:
        """Validate topic extraction and broker authentication."""
        TopicMetadataExtractor(topic_regex=self.topic_regex)

        _validate_auth_credentials(
            enabled=self.use_auth,
            username=self.mqtt_username,
            api_key=self.mqtt_api_key,
            label="MQTT",
        )

        return self

    def get_client_id(self) -> str:
        return f"{self.client_id_prefix}_{uuid.uuid4().hex[:8]}"

    def get_jittered_backoff_delay(self, attempt: int) -> float:
        delay = min(
            self.retry_base_delay * (self.retry_exponential_base**attempt),
            self.retry_max_delay,
        )
        if self.retry_jitter_enabled:
            jitter_amount = delay * self.retry_jitter_magnitude
            jitter = random.uniform(-jitter_amount, jitter_amount)
            delay += jitter
        return max(0.0, delay)

    def build_topic_extractor(self) -> TopicMetadataExtractor:
        return TopicMetadataExtractor(
            topic_regex=self.topic_regex,
        )


class MQTTSettings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        secrets_dir="/run/secrets" if Path("/run/secrets").is_dir() else None,
    )
    ENVIRONMENT: str = "development"

    # MQTT Service Configuration
    MQTT_TELEMETRY_ENABLED: bool = True

    # Broker Connection
    MQTT_BROKER_HOST: str = Field(default="localhost", min_length=1)
    MQTT_BROKER_PORT: int = Field(default=1883, ge=1, le=65535)
    MQTT_USE_TLS: bool = False
    MQTT_CA_FILE: str | None = None
    MQTT_TRANSPORT: Transport = "tcp"
    MQTT_CONNECTION_TIMEOUT: float = Field(default=30.0, ge=1.0, le=120.0)

    # Authentication
    MQTT_CLIENT_ID_PREFIX: str = Field(
        default="offkey-backend",
        min_length=1,
        max_length=50,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    MQTT_USE_AUTH: bool = False
    MQTT_USERNAME: str = ""
    MQTT_APIKEY: str = ""

    MQTT_TOPIC_REGEX: str = DEFAULT_TOPIC_REGEX

    # Connection Management
    MQTT_RECONNECT_DELAY: int = Field(default=5, ge=1, le=300)
    MQTT_MAX_RECONNECT_ATTEMPTS: int = Field(default=10, ge=1, le=100)

    # Message Processing
    MQTT_BATCH_SIZE: int = Field(default=100, ge=1, le=10_000)
    MQTT_BATCH_TIMEOUT: float = Field(default=5.0, ge=0.1, le=300.0)
    MQTT_SUBSCRIPTION_QOS: int = Field(default=1, ge=0, le=2)
    MQTT_MAX_MESSAGE_QUEUE_SIZE: int = Field(default=10_000, ge=100, le=100_000)
    MQTT_WORKER_THREADS: int = Field(default=4, ge=1, le=32)

    # Retry Configuration
    MQTT_RETRY_BASE_DELAY: float = Field(default=0.1, ge=0.01, le=10.0)
    MQTT_RETRY_MAX_DELAY: float = Field(default=5.0, ge=0.1, le=60.0)
    MQTT_RETRY_EXPONENTIAL_BASE: float = Field(default=2.0, ge=1.1, le=10.0)
    MQTT_RETRY_JITTER_ENABLED: bool = True
    MQTT_RETRY_JITTER_MAGNITUDE: float = Field(default=0.2, ge=0.0, le=0.5)

    # Background Task Intervals
    MQTT_METRICS_INTERVAL: float = Field(default=300.0, ge=30.0, le=7_200.0)
    MQTT_HEALTH_MONITOR_INTERVAL: float = Field(default=30.0, ge=5.0, le=300.0)

    # Health Monitoring
    MQTT_HEALTH_CHECK_INTERVAL: int = Field(default=35, ge=5, le=3_600)
    MQTT_HEALTH_LOG_REMINDER_INTERVAL: int = Field(default=10, ge=1, le=1_000)

    # Shutdown Configuration
    MQTT_SHUTDOWN_TIMEOUT: float = Field(default=10.0, ge=1.0, le=60.0)
    MQTT_GRACEFUL_SHUTDOWN_TIMEOUT: float = Field(
        default=30.0,
        ge=5.0,
        le=300.0,
    )

    # Health API Configuration
    MQTT_HEALTH_API_ENABLED: bool = True
    MQTT_HEALTH_API_HOST: str = Field(default="0.0.0.0", min_length=1)
    MQTT_HEALTH_API_PORT: int = Field(default=8010, ge=1, le=65535)

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        return _validate_environment(value)

    @model_validator(mode="after")
    def validate_mqtt_security_posture(self) -> Self:
        if self.ENVIRONMENT == "production":
            if not self.MQTT_USE_TLS:
                raise ValueError(
                    "MQTT_USE_TLS must be true when ENVIRONMENT=production"
                )
            if not self.MQTT_USE_AUTH:
                raise ValueError(
                    "MQTT_USE_AUTH must be true when ENVIRONMENT=production"
                )
        return self

    @property
    def config(self) -> MQTTConfig:
        return MQTTConfig(
            broker_host=self.MQTT_BROKER_HOST,
            broker_port=self.MQTT_BROKER_PORT,
            use_tls=self.MQTT_USE_TLS,
            ca_file=self.MQTT_CA_FILE,
            transport=self.MQTT_TRANSPORT,
            client_id_prefix=self.MQTT_CLIENT_ID_PREFIX,
            use_auth=self.MQTT_USE_AUTH,
            mqtt_username=self.MQTT_USERNAME,
            mqtt_api_key=self.MQTT_APIKEY,
            topic_regex=self.MQTT_TOPIC_REGEX,
            enabled=self.MQTT_TELEMETRY_ENABLED,
            reconnect_delay=self.MQTT_RECONNECT_DELAY,
            max_reconnect_attempts=self.MQTT_MAX_RECONNECT_ATTEMPTS,
            batch_size=self.MQTT_BATCH_SIZE,
            batch_timeout=self.MQTT_BATCH_TIMEOUT,
            subscription_qos=self.MQTT_SUBSCRIPTION_QOS,
            health_check_interval=self.MQTT_HEALTH_CHECK_INTERVAL,
            health_log_reminder_interval=self.MQTT_HEALTH_LOG_REMINDER_INTERVAL,
            connection_timeout=self.MQTT_CONNECTION_TIMEOUT,
            max_message_queue_size=self.MQTT_MAX_MESSAGE_QUEUE_SIZE,
            worker_threads=self.MQTT_WORKER_THREADS,
            retry_base_delay=self.MQTT_RETRY_BASE_DELAY,
            retry_max_delay=self.MQTT_RETRY_MAX_DELAY,
            retry_exponential_base=self.MQTT_RETRY_EXPONENTIAL_BASE,
            retry_jitter_enabled=self.MQTT_RETRY_JITTER_ENABLED,
            retry_jitter_magnitude=self.MQTT_RETRY_JITTER_MAGNITUDE,
            metrics_interval=self.MQTT_METRICS_INTERVAL,
            health_monitor_interval=self.MQTT_HEALTH_MONITOR_INTERVAL,
            shutdown_timeout=self.MQTT_SHUTDOWN_TIMEOUT,
            graceful_shutdown_timeout=self.MQTT_GRACEFUL_SHUTDOWN_TIMEOUT,
        )


@lru_cache(maxsize=1)
def get_mqtt_settings() -> MQTTSettings:
    """Return cached MQTT proxy settings instance."""
    return MQTTSettings()
