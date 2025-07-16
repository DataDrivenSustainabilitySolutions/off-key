"""
MQTT Service Configuration

Handles configuration for the MQTT proxy service including Firebase settings,
MQTT broker configuration, and service-specific parameters.
"""

from pydantic import BaseModel, Field
import os


class FirebaseConfig(BaseModel):
    """Firebase authentication configuration"""

    api_key: str = Field(..., description="Firebase API key")
    auth_domain: str = Field(..., description="Firebase auth domain")
    project_id: str = Field(..., description="Firebase project ID")
    storage_bucket: str = Field(..., description="Firebase storage bucket")
    messaging_sender_id: str = Field(..., description="Firebase messaging sender ID")
    app_id: str = Field(..., description="Firebase app ID")

    @classmethod
    def from_env(cls) -> "FirebaseConfig":
        """Create Firebase config from environment variables"""
        return cls(
            api_key=os.getenv("FIREBASE_API_KEY", ""),
            auth_domain=os.getenv("FIREBASE_AUTH_DOMAIN", ""),
            project_id=os.getenv("FIREBASE_PROJECT_ID", ""),
            storage_bucket=os.getenv("FIREBASE_STORAGE_BUCKET", ""),
            messaging_sender_id=os.getenv("FIREBASE_MESSAGING_SENDER_ID", ""),
            app_id=os.getenv("FIREBASE_APP_ID", ""),
        )


class MQTTConfig(BaseModel):
    """MQTT service configuration"""

    # MQTT Broker Configuration
    broker_host: str = Field(default="cloud.pionix.com", description="MQTT broker host")
    broker_port: int = Field(default=443, description="MQTT broker port")
    use_tls: bool = Field(default=True, description="Use TLS for MQTT connection")
    client_id_prefix: str = Field(
        default="offkey-backend", description="MQTT client ID prefix"
    )

    # Firebase Authentication
    firebase_email: str = Field(..., description="Firebase authentication email")
    firebase_password: str = Field(..., description="Firebase authentication password")
    firebase_config: FirebaseConfig = Field(..., description="Firebase configuration")

    # Service Configuration
    enabled: bool = Field(default=True, description="Enable MQTT telemetry service")
    reconnect_delay: int = Field(default=5, description="Reconnection delay in seconds")
    max_reconnect_attempts: int = Field(
        default=10, description="Maximum reconnection attempts"
    )

    # Message Processing
    batch_size: int = Field(
        default=100, description="Database batch size for telemetry data"
    )
    batch_timeout: float = Field(default=5.0, description="Batch timeout in seconds")
    subscription_qos: int = Field(default=1, description="MQTT subscription QoS level")

    # Health Monitoring
    health_check_interval: int = Field(
        default=30, description="Health check interval in seconds"
    )
    connection_timeout: float = Field(
        default=30.0, description="Connection timeout in seconds"
    )

    # Performance Tuning
    max_message_queue_size: int = Field(
        default=10000, description="Maximum message queue size"
    )
    worker_threads: int = Field(default=4, description="Number of worker threads")

    @classmethod
    def from_env(cls) -> "MQTTConfig":
        """Create MQTT config from environment variables"""
        firebase_config = FirebaseConfig.from_env()

        return cls(
            broker_host=os.getenv("MQTT_BROKER_HOST", "cloud.pionix.com"),
            broker_port=int(os.getenv("MQTT_BROKER_PORT", "443")),
            use_tls=os.getenv("MQTT_USE_TLS", "true").lower() == "true",
            client_id_prefix=os.getenv("MQTT_CLIENT_ID_PREFIX", "offkey-backend"),
            firebase_email=os.getenv("FIREBASE_EMAIL", ""),
            firebase_password=os.getenv("FIREBASE_PASSWORD", ""),
            firebase_config=firebase_config,
            enabled=os.getenv("MQTT_TELEMETRY_ENABLED", "true").lower() == "true",
            reconnect_delay=int(os.getenv("MQTT_RECONNECT_DELAY", "5")),
            max_reconnect_attempts=int(os.getenv("MQTT_MAX_RECONNECT_ATTEMPTS", "10")),
            batch_size=int(os.getenv("MQTT_BATCH_SIZE", "100")),
            batch_timeout=float(os.getenv("MQTT_BATCH_TIMEOUT", "5.0")),
            subscription_qos=int(os.getenv("MQTT_SUBSCRIPTION_QOS", "1")),
            health_check_interval=int(os.getenv("MQTT_HEALTH_CHECK_INTERVAL", "30")),
            connection_timeout=float(os.getenv("MQTT_CONNECTION_TIMEOUT", "30.0")),
            max_message_queue_size=int(
                os.getenv("MQTT_MAX_MESSAGE_QUEUE_SIZE", "10000")
            ),
            worker_threads=int(os.getenv("MQTT_WORKER_THREADS", "4")),
        )

    def get_websocket_url(self) -> str:
        """Get WebSocket URL for MQTT connection"""
        protocol = "wss" if self.use_tls else "ws"
        return f"{protocol}://{self.broker_host}/mqtt"

    def get_client_id(self) -> str:
        """Generate unique client ID"""
        import uuid

        return f"{self.client_id_prefix}_{uuid.uuid4().hex[:8]}"
