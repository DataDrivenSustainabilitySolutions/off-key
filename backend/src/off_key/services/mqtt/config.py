"""
MQTT Service Configuration

Handles configuration for the MQTT proxy service including API-Key authentication,
MQTT broker configuration, and service-specific parameters.
"""

from pydantic import BaseModel, field_validator, model_validator
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
