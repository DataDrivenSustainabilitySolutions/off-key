"""
MQTT Bridge Configuration

Handles configuration for the MQTT bridge service including API-Key authentication,
MQTT broker configuration, and service-specific parameters.
"""

from pydantic import SecretStr
from pydantic_settings import BaseSettings
from dotenv import find_dotenv, load_dotenv

from off_key_core.config.config import settings as base_settings

# Load default ".env" file from upper project tree
load_dotenv()

# Override with dev.env values if present
dev_env = find_dotenv("dev.env")
if dev_env:
    load_dotenv(dev_env, override=True)


class MQTTBridgeSettings(BaseSettings):
    # MQTT Bridge Service Configuration
    # Service Control
    MQTT_TELEMETRY_ENABLED: bool = True  # Enable MQTT telemetry service

    # External Broker Connection
    MQTT_EXTERNAL_HOST: str = "cloud.pionix.com"  # MQTT broker host
    MQTT_EXTERNAL_PORT: int = 443  # MQTT broker port
    MQTT_EXTERNAL_USE_TLS: bool = True  # Use TLS for MQTT connection
    MQTT_EXTERNAL_CONNECTION_TIMEOUT: float = 30.0  # Connection timeout in seconds

    # Internal Broker Connection
    MQTT_INTERNAL_HOST: str = ""  # MQTT broker host
    MQTT_INTERNAL_PORT: int = 5555  # MQTT broker port
    MQTT_INTERNAL_USE_TLS: bool = True  # Use TLS for MQTT connection
    MQTT_INTERNAL_CONNECTION_TIMEOUT: float = 30.0  # Connection timeout in seconds

    # External Authentication
    MQTT_EXTERNAL_CLIENT_ID: str = ""  # MQTT Client ID
    MQTT_EXTERNAL_CLIENT_ID_PREFIX: str = "offkey-backend"  # MQTT client ID prefix
    MQTT_EXTERNAL_USERNAME: str = ""  # MQTT authentication username (required)
    MQTT_EXTERNAL_APIKEY: SecretStr = (
        "" or base_settings.PIONIX_KEY.get_secret_value()
    )  # API key for MQTT authentication (falls back to PIONIX_KEY)

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


mqtt_settings = MQTTBridgeSettings()
