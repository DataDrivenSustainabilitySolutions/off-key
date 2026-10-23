"""
MQTT proxy configuration.
"""

import random
import uuid
from functools import lru_cache
from typing import Literal, Self

from off_key_core.config.validation import SECRETS_DIR, Environment
from off_key_core.utils.mqtt_topics import (
    DEFAULT_TOPIC_REGEX,
    TopicMetadataExtractor,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator
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

    # Message Processing
    batch_size: int = Field(ge=1, le=10_000)
    batch_timeout: float = Field(ge=0.1, le=300.0)

    connection_timeout: float = Field(ge=1.0, le=120.0)

    # Performance Tuning
    max_message_queue_size: int = Field(ge=100, le=100_000)

    # Retry Configuration
    retry_base_delay: float = Field(default=0.1, ge=0.01, le=10.0)
    retry_max_delay: float = Field(default=5.0, ge=0.1, le=60.0)
    retry_exponential_base: float = Field(default=2.0, ge=1.1, le=10.0)
    retry_jitter_enabled: bool = True
    retry_jitter_magnitude: float = Field(default=0.2, ge=0.0, le=0.5)

    # Background Task Intervals
    health_monitor_interval: float = Field(default=30.0, ge=5.0, le=300.0)

    # Shutdown Configuration
    graceful_shutdown_timeout: float = Field(default=30.0, ge=5.0, le=300.0)

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    @model_validator(mode="after")
    def validate_timing_relationships(self) -> Self:
        """Validate relationships between otherwise valid timing values."""
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


# MQTTConfig fields whose setting is not MQTT_<FIELD>.
CONFIG_RENAMES = {
    "enabled": "MQTT_TELEMETRY_ENABLED",
    "mqtt_username": "MQTT_USERNAME",
    "mqtt_api_key": "MQTT_APIKEY",
}


class MQTTSettings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        secrets_dir=SECRETS_DIR,
    )
    ENVIRONMENT: Environment = "development"

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

    # Message Processing
    MQTT_BATCH_SIZE: int = Field(default=100, ge=1, le=10_000)
    MQTT_BATCH_TIMEOUT: float = Field(default=5.0, ge=0.1, le=300.0)
    MQTT_MAX_MESSAGE_QUEUE_SIZE: int = Field(default=10_000, ge=100, le=100_000)

    # Retry Configuration
    MQTT_RETRY_BASE_DELAY: float = Field(default=0.1, ge=0.01, le=10.0)
    MQTT_RETRY_MAX_DELAY: float = Field(default=5.0, ge=0.1, le=60.0)
    MQTT_RETRY_EXPONENTIAL_BASE: float = Field(default=2.0, ge=1.1, le=10.0)
    MQTT_RETRY_JITTER_ENABLED: bool = True
    MQTT_RETRY_JITTER_MAGNITUDE: float = Field(default=0.2, ge=0.0, le=0.5)

    # Background Task Intervals
    MQTT_HEALTH_MONITOR_INTERVAL: float = Field(default=30.0, ge=5.0, le=300.0)

    # Shutdown Configuration
    MQTT_GRACEFUL_SHUTDOWN_TIMEOUT: float = Field(
        default=30.0,
        ge=5.0,
        le=300.0,
    )

    # Health API Configuration
    MQTT_HEALTH_API_ENABLED: bool = True
    MQTT_HEALTH_API_HOST: str = Field(default="0.0.0.0", min_length=1)
    MQTT_HEALTH_API_PORT: int = Field(default=8010, ge=1, le=65535)

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
            **{
                name: getattr(self, CONFIG_RENAMES.get(name, f"MQTT_{name.upper()}"))
                for name in MQTTConfig.model_fields
            }
        )


@lru_cache(maxsize=1)
def get_mqtt_settings() -> MQTTSettings:
    """Return cached MQTT proxy settings instance."""
    return MQTTSettings()
