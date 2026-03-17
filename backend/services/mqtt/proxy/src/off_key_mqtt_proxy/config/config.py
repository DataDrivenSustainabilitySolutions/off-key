"""
MQTT proxy configuration.
"""

from functools import lru_cache
import random
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Self

from off_key_core.utils.mqtt_topics import (
    DEFAULT_TOPIC_REGEX,
    TopicMetadataExtractor,
)


class MQTTConfig(BaseModel):
    """
    Validated runtime configuration for MQTT proxy.
    """

    # MQTT Broker Configuration
    broker_host: str
    broker_port: int
    use_tls: bool
    transport: str = "tcp"  # tcp | websockets
    client_id_prefix: str
    use_auth: bool
    mqtt_username: str
    mqtt_api_key: str

    # Source subscriptions
    source_topics: list[str]
    topic_regex: str = DEFAULT_TOPIC_REGEX
    topic_payload_charger_key: str = "charger_id"
    topic_payload_type_key: str = "telemetry_type"

    # Service Configuration
    enabled: bool
    reconnect_delay: int
    max_reconnect_attempts: int

    # Message Processing
    batch_size: int
    batch_timeout: float
    subscription_qos: int

    # Health Monitoring
    health_check_interval: int
    health_log_reminder_interval: int
    connection_timeout: float

    # Performance Tuning
    max_message_queue_size: int
    worker_threads: int

    # Retry Configuration
    retry_base_delay: float = 0.1
    retry_max_delay: float = 5.0
    retry_exponential_base: float = 2.0
    retry_jitter_enabled: bool = True
    retry_jitter_magnitude: float = 0.2

    # Background Task Intervals
    cleanup_interval: float = 60.0
    metrics_interval: float = 300.0
    health_monitor_interval: float = 30.0

    # Shutdown Configuration
    shutdown_timeout: float = 10.0
    graceful_shutdown_timeout: float = 30.0

    # Bridge Configuration
    enable_bridge: bool = False
    bridge_broker_host: str = ""
    bridge_broker_port: int = 1883
    bridge_use_tls: bool = False
    bridge_transport: str = "tcp"
    bridge_client_id_prefix: str = "offkey-bridge"
    bridge_use_auth: bool = False
    bridge_username: str = ""
    bridge_api_key: str = ""
    bridge_topic_mapping: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    @field_validator("broker_port", "bridge_broker_port")
    @classmethod
    def validate_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return value

    @field_validator("transport", "bridge_transport")
    @classmethod
    def validate_transport(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"tcp", "websockets"}:
            raise ValueError("Transport must be one of: tcp, websockets")
        return normalized

    @field_validator("worker_threads")
    @classmethod
    def validate_worker_threads(cls, value: int) -> int:
        if not 1 <= value <= 32:
            raise ValueError("Worker threads must be between 1 and 32")
        return value

    @field_validator("batch_size")
    @classmethod
    def validate_batch_size(cls, value: int) -> int:
        if not 1 <= value <= 10000:
            raise ValueError("Batch size must be between 1 and 10000")
        return value

    @field_validator("batch_timeout")
    @classmethod
    def validate_batch_timeout(cls, value: float) -> float:
        if not 0.1 <= value <= 300.0:
            raise ValueError("Batch timeout must be between 0.1 and 300.0 seconds")
        return value

    @field_validator("subscription_qos")
    @classmethod
    def validate_subscription_qos(cls, value: int) -> int:
        if value not in {0, 1, 2}:
            raise ValueError("MQTT QoS must be 0, 1, or 2")
        return value

    @field_validator("reconnect_delay")
    @classmethod
    def validate_reconnect_delay(cls, value: int) -> int:
        if not 1 <= value <= 300:
            raise ValueError("Reconnect delay must be between 1 and 300 seconds")
        return value

    @field_validator("max_reconnect_attempts")
    @classmethod
    def validate_max_reconnect_attempts(cls, value: int) -> int:
        if not 1 <= value <= 100:
            raise ValueError("Max reconnect attempts must be between 1 and 100")
        return value

    @field_validator("health_check_interval")
    @classmethod
    def validate_health_check_interval(cls, value: int) -> int:
        if not 5 <= value <= 3600:
            raise ValueError("Health check interval must be between 5 and 3600 seconds")
        return value

    @field_validator("health_log_reminder_interval")
    @classmethod
    def validate_health_log_reminder_interval(cls, value: int) -> int:
        if not 1 <= value <= 1000:
            raise ValueError(
                "Health log reminder interval must be between 1 and 1000 checks"
            )
        return value

    @field_validator("connection_timeout")
    @classmethod
    def validate_connection_timeout(cls, value: float) -> float:
        if not 1.0 <= value <= 120.0:
            raise ValueError("Connection timeout must be between 1.0 and 120.0 seconds")
        return value

    @field_validator("max_message_queue_size")
    @classmethod
    def validate_max_message_queue_size(cls, value: int) -> int:
        if not 100 <= value <= 100000:
            raise ValueError("Max message queue size must be between 100 and 100000")
        return value

    @field_validator("shutdown_timeout")
    @classmethod
    def validate_shutdown_timeout(cls, value: float) -> float:
        if not 1.0 <= value <= 60.0:
            raise ValueError("Shutdown timeout must be between 1.0 and 60.0 seconds")
        return value

    @field_validator("graceful_shutdown_timeout")
    @classmethod
    def validate_graceful_shutdown_timeout(cls, value: float) -> float:
        if not 5.0 <= value <= 300.0:
            raise ValueError(
                "Graceful shutdown timeout must be between 5.0 and 300.0 seconds"
            )
        return value

    @field_validator("retry_base_delay")
    @classmethod
    def validate_retry_base_delay(cls, value: float) -> float:
        if not 0.01 <= value <= 10.0:
            raise ValueError("Retry base delay must be between 0.01 and 10.0 seconds")
        return value

    @field_validator("retry_max_delay")
    @classmethod
    def validate_retry_max_delay(cls, value: float) -> float:
        if not 0.1 <= value <= 60.0:
            raise ValueError("Retry max delay must be between 0.1 and 60.0 seconds")
        return value

    @field_validator("retry_exponential_base")
    @classmethod
    def validate_retry_exponential_base(cls, value: float) -> float:
        if not 1.1 <= value <= 10.0:
            raise ValueError("Retry exponential base must be between 1.1 and 10.0")
        return value

    @field_validator("retry_jitter_magnitude")
    @classmethod
    def validate_retry_jitter_magnitude(cls, value: float) -> float:
        if not 0.0 <= value <= 0.5:
            raise ValueError(
                "Retry jitter magnitude must be between 0.0 (0%) and 0.5 (50%)"
            )
        return value

    @field_validator("cleanup_interval")
    @classmethod
    def validate_cleanup_interval(cls, value: float) -> float:
        if not 10.0 <= value <= 3600.0:
            raise ValueError("Cleanup interval must be between 10.0 and 3600.0 seconds")
        return value

    @field_validator("metrics_interval")
    @classmethod
    def validate_metrics_interval(cls, value: float) -> float:
        if not 30.0 <= value <= 7200.0:
            raise ValueError("Metrics interval must be between 30.0 and 7200.0 seconds")
        return value

    @field_validator("health_monitor_interval")
    @classmethod
    def validate_health_monitor_interval(cls, value: float) -> float:
        if not 5.0 <= value <= 300.0:
            raise ValueError(
                "Health monitor interval must be between 5.0 and 300.0 seconds"
            )
        return value

    @field_validator("client_id_prefix", "bridge_client_id_prefix")
    @classmethod
    def validate_client_id_prefix(cls, value: str) -> str:
        if not value or len(value) > 50:
            raise ValueError("Client ID prefix must be non-empty and max 50 characters")
        if not value.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                "Client ID prefix must contain only alphanumeric characters, "
                "hyphens, and underscores"
            )
        return value

    @field_validator("source_topics")
    @classmethod
    def validate_source_topics(cls, value: list[str]) -> list[str]:
        normalized = [topic.strip() for topic in value if topic and topic.strip()]
        if not normalized:
            raise ValueError("At least one source topic filter is required")
        return normalized

    @field_validator("topic_payload_charger_key", "topic_payload_type_key")
    @classmethod
    def validate_payload_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Payload metadata keys must be non-empty")
        return normalized

    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
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

        # Validate extraction contract early to fail fast.
        TopicMetadataExtractor(
            topic_regex=self.topic_regex,
            payload_charger_key=self.topic_payload_charger_key,
            payload_type_key=self.topic_payload_type_key,
        )

        if self.use_auth:
            if not self.mqtt_username.strip():
                raise ValueError("MQTT username is required when MQTT auth is enabled")
            if len(self.mqtt_api_key.strip()) < 10:
                raise ValueError(
                    "MQTT API key must be at least 10 characters when auth is enabled"
                )

        if self.enable_bridge:
            if not self.bridge_broker_host.strip():
                raise ValueError(
                    "Bridge broker host is required when bridge is enabled"
                )

            if self.bridge_use_auth:
                if not self.bridge_username.strip():
                    raise ValueError(
                        "Bridge username is required when bridge auth is enabled"
                    )
                if len(self.bridge_api_key.strip()) < 10:
                    raise ValueError(
                        "Bridge API key must be at least 10 characters when "
                        "bridge auth is enabled"
                    )

        return self

    def get_websocket_url(self) -> str:
        protocol = "wss" if self.use_tls else "ws"
        return f"{protocol}://{self.broker_host}:{self.broker_port}/mqtt"

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
            payload_charger_key=self.topic_payload_charger_key,
            payload_type_key=self.topic_payload_type_key,
        )


class MQTTSettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")
    ENVIRONMENT: str = "development"

    # MQTT Service Configuration
    MQTT_TELEMETRY_ENABLED: bool = True

    # Broker Connection
    MQTT_BROKER_HOST: str = "localhost"
    MQTT_BROKER_PORT: int = 1883
    MQTT_USE_TLS: bool = False
    MQTT_TRANSPORT: str = "tcp"
    MQTT_CONNECTION_TIMEOUT: float = 30.0

    # Authentication
    MQTT_CLIENT_ID_PREFIX: str = "offkey-backend"
    MQTT_USE_AUTH: bool = False
    MQTT_USERNAME: str = ""
    MQTT_APIKEY: str = ""

    # Source Subscriptions
    MQTT_SOURCE_TOPICS: str = "charger/+/live-telemetry/#"
    MQTT_TOPIC_REGEX: str = DEFAULT_TOPIC_REGEX
    MQTT_TOPIC_PAYLOAD_CHARGER_KEY: str = "charger_id"
    MQTT_TOPIC_PAYLOAD_TYPE_KEY: str = "telemetry_type"

    # Connection Management
    MQTT_RECONNECT_DELAY: int = 5
    MQTT_MAX_RECONNECT_ATTEMPTS: int = 10

    # Message Processing
    MQTT_BATCH_SIZE: int = 100
    MQTT_BATCH_TIMEOUT: float = 5.0
    MQTT_SUBSCRIPTION_QOS: int = 1
    MQTT_MAX_MESSAGE_QUEUE_SIZE: int = 10000
    MQTT_WORKER_THREADS: int = 4

    # Retry Configuration
    MQTT_RETRY_BASE_DELAY: float = 0.1
    MQTT_RETRY_MAX_DELAY: float = 5.0
    MQTT_RETRY_EXPONENTIAL_BASE: float = 2.0
    MQTT_RETRY_JITTER_ENABLED: bool = True
    MQTT_RETRY_JITTER_MAGNITUDE: float = 0.2

    # Background Task Intervals
    MQTT_CLEANUP_INTERVAL: float = 60.0
    MQTT_METRICS_INTERVAL: float = 300.0
    MQTT_HEALTH_MONITOR_INTERVAL: float = 30.0

    # Health Monitoring
    MQTT_HEALTH_CHECK_INTERVAL: int = 35
    MQTT_HEALTH_LOG_REMINDER_INTERVAL: int = 10

    # Shutdown Configuration
    MQTT_SHUTDOWN_TIMEOUT: float = 10.0
    MQTT_GRACEFUL_SHUTDOWN_TIMEOUT: float = 30.0

    # Bridge Configuration
    MQTT_ENABLE_BRIDGE: bool = False
    MQTT_BRIDGE_BROKER_HOST: str = ""
    MQTT_BRIDGE_BROKER_PORT: int = 1883
    MQTT_BRIDGE_USE_TLS: bool = False
    MQTT_BRIDGE_TRANSPORT: str = "tcp"
    MQTT_BRIDGE_CLIENT_ID_PREFIX: str = "offkey-bridge"
    MQTT_BRIDGE_USE_AUTH: bool = False
    MQTT_BRIDGE_USERNAME: str = ""
    MQTT_BRIDGE_APIKEY: str = ""

    # Health API Configuration
    MQTT_HEALTH_API_ENABLED: bool = True
    MQTT_HEALTH_API_HOST: str = "0.0.0.0"
    MQTT_HEALTH_API_PORT: int = 8010

    @field_validator("MQTT_HEALTH_API_PORT")
    @classmethod
    def validate_health_api_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("MQTT health API port must be between 1 and 65535")
        return value

    @field_validator("MQTT_SOURCE_TOPICS")
    @classmethod
    def validate_source_topics(cls, value: str) -> str:
        if not value.strip():
            raise ValueError(
                "MQTT_SOURCE_TOPICS must contain at least one topic filter"
            )
        return value

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"development", "test", "staging", "production"}
        if normalized not in allowed:
            allowed_text = ", ".join(sorted(allowed))
            raise ValueError(f"ENVIRONMENT must be one of: {allowed_text}")
        return normalized

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
        source_topics = [
            topic.strip()
            for topic in self.MQTT_SOURCE_TOPICS.split(",")
            if topic.strip()
        ]

        return MQTTConfig(
            broker_host=self.MQTT_BROKER_HOST,
            broker_port=self.MQTT_BROKER_PORT,
            use_tls=self.MQTT_USE_TLS,
            transport=self.MQTT_TRANSPORT,
            client_id_prefix=self.MQTT_CLIENT_ID_PREFIX,
            use_auth=self.MQTT_USE_AUTH,
            mqtt_username=self.MQTT_USERNAME,
            mqtt_api_key=self.MQTT_APIKEY,
            source_topics=source_topics,
            topic_regex=self.MQTT_TOPIC_REGEX,
            topic_payload_charger_key=self.MQTT_TOPIC_PAYLOAD_CHARGER_KEY,
            topic_payload_type_key=self.MQTT_TOPIC_PAYLOAD_TYPE_KEY,
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
            cleanup_interval=self.MQTT_CLEANUP_INTERVAL,
            metrics_interval=self.MQTT_METRICS_INTERVAL,
            health_monitor_interval=self.MQTT_HEALTH_MONITOR_INTERVAL,
            shutdown_timeout=self.MQTT_SHUTDOWN_TIMEOUT,
            graceful_shutdown_timeout=self.MQTT_GRACEFUL_SHUTDOWN_TIMEOUT,
            enable_bridge=self.MQTT_ENABLE_BRIDGE,
            bridge_broker_host=self.MQTT_BRIDGE_BROKER_HOST,
            bridge_broker_port=self.MQTT_BRIDGE_BROKER_PORT,
            bridge_use_tls=self.MQTT_BRIDGE_USE_TLS,
            bridge_transport=self.MQTT_BRIDGE_TRANSPORT,
            bridge_client_id_prefix=self.MQTT_BRIDGE_CLIENT_ID_PREFIX,
            bridge_use_auth=self.MQTT_BRIDGE_USE_AUTH,
            bridge_username=self.MQTT_BRIDGE_USERNAME,
            bridge_api_key=self.MQTT_BRIDGE_APIKEY,
        )


@lru_cache(maxsize=1)
def get_mqtt_settings() -> MQTTSettings:
    """Return cached MQTT proxy settings instance."""
    return MQTTSettings()
