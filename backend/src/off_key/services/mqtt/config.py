"""
MQTT Service Configuration

Handles configuration for the MQTT proxy service including API-Key authentication,
MQTT broker configuration, and service-specific parameters.
"""

from pydantic import BaseModel


class MQTTConfig(BaseModel):
    """MQTT service configuration"""

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

    def get_websocket_url(self) -> str:
        """Get WebSocket URL for MQTT connection"""
        protocol = "wss" if self.use_tls else "ws"
        return f"{protocol}://{self.broker_host}/mqtt"

    def get_client_id(self) -> str:
        """Generate unique client ID"""
        import uuid

        return f"{self.client_id_prefix}_{uuid.uuid4().hex[:8]}"
