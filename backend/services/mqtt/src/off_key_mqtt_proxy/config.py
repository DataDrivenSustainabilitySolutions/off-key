"""
MQTT Service Configuration

Handles configuration for the MQTT proxy service including API-Key authentication,
MQTT broker configuration, and service-specific parameters.
"""
import random
from pydantic import BaseModel, field_validator, model_validator
from off_key_core.config.config import settings
from typing import Self


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

    @property
    def mqtt_config(self) -> "MQTTConfig":
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

        # Use PIONIX_KEY as fallback for MQTT_APIKEY if empty
        mqtt_api_key = self.mqtt_api_key or settings.PIONIX_KEY

        # TODO: (Re)define default values
        return MQTTConfig(
            broker_host=self.broker_host,
            broker_port=self.broker_port,
            use_tls=self.use_tls,
            client_id_prefix=self.client_id_prefix,
            mqtt_username=self.mqtt_username,
            mqtt_api_key=mqtt_api_key,
            enabled=self.enabled,
            reconnect_delay=self.reconnect_delay,
            max_reconnect_attempts=self.max_reconnect_attempts,
            batch_size=self.batch_size,
            batch_timeout=self.batch_timeout,
            subscription_qos=self.subscription_qos,
            health_check_interval=self.health_check_interval,
            health_log_reminder_interval=self.health_log_reminder_interval,
            connection_timeout=self.connection_timeout,
            max_message_queue_size=self.max_message_queue_size,
            worker_threads=self.worker_threads,
            shutdown_timeout=self.shutdown_timeout,
            graceful_shutdown_timeout = self.graceful_shutdown_timeout,
        )
