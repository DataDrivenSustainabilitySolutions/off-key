"""
MQTT Proxy Configuration

Handles configuration for the MQTT proxy service including API-Key authentication,
MQTT broker configuration, and service-specific parameters.
"""
import random
from pydantic import BaseModel, field_validator, model_validator
from pydantic_settings import BaseSettings

from off_key_core.config.config import settings
from typing import Self, Dict
from dotenv import find_dotenv, load_dotenv

# Load default ".env" file from upper project tree
load_dotenv()

# Override with dev.env values if present
dev_env = find_dotenv("dev.env")
if dev_env:
    load_dotenv(dev_env, override=True)


class MQTTConfig(BaseModel):
    """
    MQTT service configuration with business logic validation.

    This is a pure data model containing validated configuration values
    for the MQTT proxy service.
    """

    # MQTT Broker Configuration
    broker_host: str
    broker_port: int
    use_tls: bool
    client_id_prefix: str

    # API-Key Authentication
    mqtt_username: str
    mqtt_api_key: str

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
    retry_base_delay: float = 0.1  # Base delay for exponential backoff
    retry_max_delay: float = 5.0  # Maximum delay cap for retries
    retry_exponential_base: float = 2.0  # Exponential backoff base (standard is 2.0)
    retry_jitter_enabled: bool = True  # Enable jitter to prevent thundering herd
    retry_jitter_magnitude: float = 0.2  # Jitter magnitude (±20% range)

    # Background Task Intervals
    cleanup_interval: float = 60.0  # Cleanup task interval in seconds
    metrics_interval: float = 300.0  # Metrics reporting interval in seconds
    health_monitor_interval: float = 30.0  # Health monitoring interval in seconds

    # Shutdown Configuration
    shutdown_timeout: float = 10.0  # Default timeout for component shutdown
    graceful_shutdown_timeout: float = 30.0  # Total graceful shutdown timeout

    # Bridge Configuration
    enable_bridge: bool = False  # Enable MQTT bridge to another broker
    bridge_broker_host: str = ""  # Bridge target broker host
    bridge_broker_port: int = 1883  # Bridge target broker port
    bridge_use_tls: bool = False  # Use TLS for bridge connection
    bridge_client_id_prefix: str = "offkey-bridge"  # Bridge client ID prefix
    bridge_use_auth: bool = True  # Enable/disable bridge authentication
    bridge_username: str = ""  # Bridge authentication username
    bridge_api_key: str = ""  # Bridge API key
    bridge_topic_mapping: Dict[str, str] = {}  # Source topic -> target topic mapping

    class Config:
        # Prevent extra fields
        extra = "forbid"
        # Validate assignment to ensure changes maintain constraints
        validate_assignment = True

    @field_validator("broker_port")
    @classmethod
    def validate_broker_port(cls, v: int) -> int:
        """Validate MQTT broker port is in valid range"""
        if not 1 <= v <= 65535:
            raise ValueError("MQTT broker port must be between 1 and 65535")
        return v

    @field_validator("worker_threads")
    @classmethod
    def validate_worker_threads(cls, v: int) -> int:
        """Validate worker threads is reasonable for MQTT processing"""
        if not 1 <= v <= 32:
            raise ValueError("Worker threads must be between 1 and 32")
        return v

    @field_validator("batch_size")
    @classmethod
    def validate_batch_size(cls, v: int) -> int:
        """Validate batch size for database operations"""
        if not 1 <= v <= 10000:
            raise ValueError("Batch size must be between 1 and 10000")
        return v

    @field_validator("batch_timeout")
    @classmethod
    def validate_batch_timeout(cls, v: float) -> float:
        """Validate batch timeout is reasonable"""
        if not 0.1 <= v <= 300.0:
            raise ValueError("Batch timeout must be between 0.1 and 300.0 seconds")
        return v

    @field_validator("subscription_qos")
    @classmethod
    def validate_subscription_qos(cls, v: int) -> int:
        """Validate MQTT QoS level"""
        if v not in [0, 1, 2]:
            raise ValueError(
                "MQTT QoS must be 0 (at most once), "
                "1 (at least once), "
                "or 2 (exactly once)"
            )
        return v

    @field_validator("reconnect_delay")
    @classmethod
    def validate_reconnect_delay(cls, v: int) -> int:
        """Validate reconnection delay"""
        if not 1 <= v <= 300:
            raise ValueError("Reconnect delay must be between 1 and 300 seconds")
        return v

    @field_validator("max_reconnect_attempts")
    @classmethod
    def validate_max_reconnect_attempts(cls, v: int) -> int:
        """Validate maximum reconnection attempts"""
        if not 1 <= v <= 100:
            raise ValueError("Max reconnect attempts must be between 1 and 100")
        return v

    @field_validator("health_check_interval")
    @classmethod
    def validate_health_check_interval(cls, v: int) -> int:
        """Validate health check interval"""
        if not 5 <= v <= 3600:
            raise ValueError("Health check interval must be between 5 and 3600 seconds")
        return v

    @field_validator("health_log_reminder_interval")
    @classmethod
    def validate_health_log_reminder_interval(cls, v: int) -> int:
        """Validate health log reminder interval"""
        if not 1 <= v <= 1000:
            raise ValueError(
                "Health log reminder interval must be between 1 and 1000 checks"
            )
        return v

    @field_validator("connection_timeout")
    @classmethod
    def validate_connection_timeout(cls, v: float) -> float:
        """Validate connection timeout"""
        if not 1.0 <= v <= 120.0:
            raise ValueError("Connection timeout must be between 1.0 and 120.0 seconds")
        return v

    @field_validator("max_message_queue_size")
    @classmethod
    def validate_max_message_queue_size(cls, v: int) -> int:
        """Validate maximum message queue size"""
        if not 100 <= v <= 100000:
            raise ValueError("Max message queue size must be between 100 and 100000")
        return v

    @field_validator("shutdown_timeout")
    @classmethod
    def validate_shutdown_timeout(cls, v: float) -> float:
        """Validate component shutdown timeout"""
        if not 1.0 <= v <= 60.0:
            raise ValueError("Shutdown timeout must be between 1.0 and 60.0 seconds")
        return v

    @field_validator("graceful_shutdown_timeout")
    @classmethod
    def validate_graceful_shutdown_timeout(cls, v: float) -> float:
        """Validate total graceful shutdown timeout"""
        if not 5.0 <= v <= 300.0:
            raise ValueError(
                "Graceful shutdown timeout must be between 5.0 and 300.0 seconds"
            )
        return v

    @field_validator("retry_base_delay")
    @classmethod
    def validate_retry_base_delay(cls, v: float) -> float:
        """Validate retry base delay"""
        if not 0.01 <= v <= 10.0:
            raise ValueError("Retry base delay must be between 0.01 and 10.0 seconds")
        return v

    @field_validator("retry_max_delay")
    @classmethod
    def validate_retry_max_delay(cls, v: float) -> float:
        """Validate retry maximum delay"""
        if not 0.1 <= v <= 60.0:
            raise ValueError("Retry max delay must be between 0.1 and 60.0 seconds")
        return v

    @field_validator("retry_exponential_base")
    @classmethod
    def validate_retry_exponential_base(cls, v: float) -> float:
        """Validate retry exponential base"""
        if not 1.1 <= v <= 10.0:
            raise ValueError("Retry exponential base must be between 1.1 and 10.0")
        return v

    @field_validator("retry_jitter_magnitude")
    @classmethod
    def validate_retry_jitter_magnitude(cls, v: float) -> float:
        """Validate retry jitter magnitude"""
        if not 0.0 <= v <= 0.5:
            raise ValueError(
                "Retry jitter magnitude must be between 0.0 (0%) and 0.5 (50%)"
            )
        return v

    @field_validator("cleanup_interval")
    @classmethod
    def validate_cleanup_interval(cls, v: float) -> float:
        """Validate cleanup interval"""
        if not 10.0 <= v <= 3600.0:
            raise ValueError("Cleanup interval must be between 10.0 and 3600.0 seconds")
        return v

    @field_validator("metrics_interval")
    @classmethod
    def validate_metrics_interval(cls, v: float) -> float:
        """Validate metrics interval"""
        if not 30.0 <= v <= 7200.0:
            raise ValueError("Metrics interval must be between 30.0 and 7200.0 seconds")
        return v

    @field_validator("health_monitor_interval")
    @classmethod
    def validate_health_monitor_interval(cls, v: float) -> float:
        """Validate health monitor interval"""
        if not 5.0 <= v <= 300.0:
            raise ValueError(
                "Health monitor interval must be between 5.0 and 300.0 seconds"
            )
        return v

    @field_validator("client_id_prefix")
    @classmethod
    def validate_client_id_prefix(cls, v: str) -> str:
        """Validate client ID prefix format"""
        if not v or len(v) > 50:
            raise ValueError("Client ID prefix must be non-empty and max 50 characters")
        # MQTT client ID restrictions: alphanumeric and limited special chars
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                "Client ID prefix must contain only "
                "alphanumeric characters, hyphens, and underscores"
            )
        return v

    @field_validator("mqtt_username")
    @classmethod
    def validate_mqtt_username(cls, v: str) -> str:
        """Validate MQTT username"""
        if not v or len(v) > 100:
            raise ValueError("MQTT username must be non-empty and max 100 characters")
        return v

    @field_validator("mqtt_api_key")
    @classmethod
    def validate_mqtt_api_key(cls, v: str) -> str:
        """Validate MQTT API key"""
        if not v or len(v) < 10:
            raise ValueError(
                "MQTT API key must be non-empty and at least 10 characters"
            )
        return v

    @field_validator("bridge_broker_port")
    @classmethod
    def validate_bridge_broker_port(cls, v: int) -> int:
        """Validate bridge broker port is in valid range"""
        if not 1 <= v <= 65535:
            raise ValueError("Bridge broker port must be between 1 and 65535")
        return v

    @field_validator("bridge_client_id_prefix")
    @classmethod
    def validate_bridge_client_id_prefix(cls, v: str) -> str:
        """Validate bridge client ID prefix format"""
        if v and len(v) > 50:
            raise ValueError("Bridge client ID prefix must be max 50 characters")
        if v and not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError(
                "Bridge client ID prefix must contain only "
                "alphanumeric characters, hyphens, and underscores"
            )
        return v

    @model_validator(mode="after")
    def validate_timeout_consistency(self) -> Self:
        """Validate that timeouts are consistent with explicit safety margins"""
        # Define minimum safe margin for reliable health monitoring
        MINIMUM_HEALTH_CHECK_MARGIN_SECONDS = 5

        # Health check interval must exceed connection timeout by minimum margin
        if self.health_check_interval < (
            self.connection_timeout + MINIMUM_HEALTH_CHECK_MARGIN_SECONDS
        ):
            raise ValueError(
                f"Health check interval ({self.health_check_interval}s) must be >"
                f"{MINIMUM_HEALTH_CHECK_MARGIN_SECONDS}s than connection timeout "
                f"({self.connection_timeout}s) to ensure reliable health monitoring. "
                f"Required minimum: "
                f"{self.connection_timeout + MINIMUM_HEALTH_CHECK_MARGIN_SECONDS}s"
            )

        # Batch timeout should be reasonable compared to connection timeout
        if self.batch_timeout >= self.connection_timeout:
            raise ValueError(
                f"Batch timeout ({self.batch_timeout}s) should be less than "
                f"connection timeout ({self.connection_timeout}s)"
                f" to prevent processing delays"
            )

        # Retry max delay must be greater than base delay
        if self.retry_max_delay <= self.retry_base_delay:
            raise ValueError(
                f"Retry max delay ({self.retry_max_delay}s) must be greater than "
                f"retry base delay ({self.retry_base_delay}s)"
            )

        return self

    def get_websocket_url(self) -> str:
        """Get WebSocket URL for MQTT connection"""
        protocol = "wss" if self.use_tls else "ws"
        return f"{protocol}://{self.broker_host}/mqtt"

    def get_client_id(self) -> str:
        """Generate unique client ID"""
        import uuid

        return f"{self.client_id_prefix}_{uuid.uuid4().hex[:8]}"

    def get_jittered_backoff_delay(self, attempt: int) -> float:
        """
        Calculates exponential backoff delay with cap and optional jitter.
        Zero magic numbers - fully self-documenting implementation.

        Args:
            attempt: Retry attempt number (0-based)

        Returns:
            Calculated delay in seconds, guaranteed non-negative
        """
        # Capped exponential backoff using configurable base
        delay = min(
            self.retry_base_delay * (self.retry_exponential_base**attempt),
            self.retry_max_delay,
        )

        # Add symmetric jitter if enabled
        if self.retry_jitter_enabled:
            jitter_amount = delay * self.retry_jitter_magnitude
            jitter = random.uniform(-jitter_amount, jitter_amount)  # Clear intent
            delay += jitter

        # Ensure non-negative delay
        return max(0.0, delay)


class MQTTSettings(BaseSettings):
    # MQTT Service Configuration
    # Service Control
    MQTT_TELEMETRY_ENABLED: bool = True  # Enable MQTT telemetry service

    # Broker Connection
    MQTT_BROKER_HOST: str = "cloud.pionix.com"  # MQTT broker host
    MQTT_BROKER_PORT: int = 443  # MQTT broker port
    MQTT_USE_TLS: bool = True  # Use TLS for MQTT connection
    MQTT_CONNECTION_TIMEOUT: float = 30.0  # Connection timeout in seconds

    # Authentication
    MQTT_CLIENT_ID: str = "" # MQTT Client ID
    MQTT_CLIENT_ID_PREFIX: str = "offkey-backend"  # MQTT client ID prefix
    MQTT_USERNAME: str  # MQTT authentication username (required)
    MQTT_APIKEY: str = ""  # API key for MQTT authentication (falls back to PIONIX_KEY)

    # Connection Management
    MQTT_RECONNECT_DELAY: int = 5  # Reconnection delay in seconds
    MQTT_MAX_RECONNECT_ATTEMPTS: int = 10  # Maximum reconnection attempts

    # Message Processing
    MQTT_BATCH_SIZE: int = 100  # Database batch size for MQTT messages
    MQTT_BATCH_TIMEOUT: float = 5.0  # Batch timeout in seconds
    MQTT_SUBSCRIPTION_QOS: int = 1  # MQTT subscription QoS level
    MQTT_MAX_MESSAGE_QUEUE_SIZE: int = 10000  # Maximum message queue size
    MQTT_WORKER_THREADS: int = 4  # Number of worker threads

    # Health Monitoring
    MQTT_HEALTH_CHECK_INTERVAL: int = 35  # Health check interval in seconds
    MQTT_HEALTH_LOG_REMINDER_INTERVAL: int = (
        10  # Re-log persistent unhealthy states every N health checks
    )

    # Shutdown Configuration
    MQTT_SHUTDOWN_TIMEOUT: float = 10.0  # Component shutdown timeout in seconds
    MQTT_GRACEFUL_SHUTDOWN_TIMEOUT: float = 30.0  # Total graceful shutdown timeout

    # Bridge Configuration
    MQTT_ENABLE_BRIDGE: bool = False  # Enable MQTT bridge to another broker
    MQTT_BRIDGE_BROKER_HOST: str = ""  # Bridge target broker host
    MQTT_BRIDGE_BROKER_PORT: int = 1883  # Bridge target broker port
    MQTT_BRIDGE_USE_TLS: bool = False  # Use TLS for bridge connection
    MQTT_BRIDGE_CLIENT_ID_PREFIX: str = "offkey-bridge"  # Bridge client ID prefix
    MQTT_BRIDGE_USE_AUTH: bool = True  # Enable/disable bridge authentication
    MQTT_BRIDGE_USERNAME: str = ""  # Bridge authentication username
    MQTT_BRIDGE_APIKEY: str = ""  # Bridge API key (falls back to PIONIX_KEY)

    @property
    def config(self) -> "MQTTConfig":
        """
        Create MQTTConfig instance from centralized settings.

        This property demonstrates the dual-config pattern: environment parsing
        happens here, while business logic validation occurs in MQTTConfig.

        Features:
        - Fallback logic for MQTT_APIKEY (uses PIONIX_KEY if empty)
        - Centralized mapping from environment variables to config objects
        - Late import to avoid circular dependencies

        Returns:
            MQTTConfig: Validated MQTT service config with business logic constraints
        """
        return MQTTConfig(
            broker_host=self.MQTT_BROKER_HOST,
            broker_port=self.MQTT_BROKER_PORT,
            use_tls=self.MQTT_USE_TLS,
            client_id_prefix=self.MQTT_CLIENT_ID_PREFIX,
            mqtt_username=self.MQTT_USERNAME,
            mqtt_api_key=self.MQTT_APIKEY or settings.PIONIX_KEY.get_secret_value(),
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
            shutdown_timeout=self.MQTT_SHUTDOWN_TIMEOUT,
            graceful_shutdown_timeout=self.MQTT_GRACEFUL_SHUTDOWN_TIMEOUT,
            enable_bridge=self.MQTT_ENABLE_BRIDGE,
            bridge_broker_host=self.MQTT_BRIDGE_BROKER_HOST,
            bridge_broker_port=self.MQTT_BRIDGE_BROKER_PORT,
            bridge_use_tls=self.MQTT_BRIDGE_USE_TLS,
            bridge_client_id_prefix=self.MQTT_BRIDGE_CLIENT_ID_PREFIX,
            bridge_use_auth=self.MQTT_BRIDGE_USE_AUTH,
            bridge_username=self.MQTT_BRIDGE_USERNAME,
            bridge_api_key=self.MQTT_BRIDGE_APIKEY
        )

mqtt_settings = MQTTSettings()
