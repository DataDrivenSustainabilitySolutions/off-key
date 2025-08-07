from pydantic_settings import BaseSettings
from pydantic import field_validator, FieldValidationInfo
from dotenv import find_dotenv, load_dotenv
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..services.mqtt.config import MQTTConfig
    from .client.pionix_config import PionixConfig

# Load default ".env" file from upper project tree
load_dotenv()

# Override with dev.env values if present
dev_env = find_dotenv("dev.env")
if dev_env:
    load_dotenv(dev_env, override=True)


class Settings(BaseSettings):
    """
    Centralized app settings with environment variable parsing.

    This class manages all environment variables. It follows the dual-config pattern
    where this class handles environment parsing and validation, while service-specific
    config classes (MQTTConfig, PionixConfig) handle business logic validation.

    Environment Variable Naming Convention:
    - Use uppercase with underscores: MQTT_BROKER_HOST
    - Group by service prefix: MQTT_, PIONIX_, SYNC_
    - Use descriptive names: HEALTH_CHECK_INTERVAL vs INTERVAL

    Usage:
        settings = Settings()  # Loads from environment
        mqtt_config = settings.mqtt_config  # Service-specific config
    """

    # Application Configuration
    APP_NAME: str
    DEBUG: bool = False  # Set to True in development for SQL logging

    # API Provider Configuration
    CHARGER_API_PROVIDER: str = "pionix"  # Default to pionix, can be overridden

    # Authentication & Security Configuration
    JWT_SECRET: str
    JWT_VERIFICATION_SECRET: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    SUPERUSER_MAIL: str

    # Email Service Configuration
    EMAIL_USERNAME: str
    EMAIL_PASSWORD: str
    EMAIL_FROM: str
    FRONTEND_BASE_URL: str
    SMTP_SERVER: str
    SMTP_PORT: int
    MAIL_STARTTLS: bool
    MAIL_SSL_TLS: bool
    USE_CREDENTIALS: bool
    VALIDATE_CERTS: bool

    # Database Configuration
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_PORT: str
    POSTGRES_HOST: str  # 'postgres' if connecting from another container

    # Pionix API Configuration
    PIONIX_KEY: str
    PIONIX_USER_AGENT: str

    # Pionix API Endpoint Templates
    PIONIX_CHARGERS_ENDPOINT: str = "chargers"
    PIONIX_DEVICE_MODEL_ENDPOINT: str = "chargers/{charger_id}/deviceModel"
    PIONIX_TELEMETRY_ENDPOINT: str = "chargers/{charger_id}/telemetry/{hierarchy}"

    # Alerting Configuration
    ANOMALY_ALERT_RECIPIENTS: str = "admin@example.com"  # Comma-separated list

    # MQTT Service Configuration
    # Service Control
    MQTT_TELEMETRY_ENABLED: bool = True  # Enable MQTT telemetry service

    # Broker Connection
    MQTT_BROKER_HOST: str = "cloud.pionix.com"  # MQTT broker host
    MQTT_BROKER_PORT: int = 443  # MQTT broker port
    MQTT_USE_TLS: bool = True  # Use TLS for MQTT connection
    MQTT_CONNECTION_TIMEOUT: float = 30.0  # Connection timeout in seconds

    # Authentication
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

    # MQTT Topic Templates
    PIONIX_MQTT_TELEMETRY_TOPIC: str = "charger/{charger_id}/live-telemetry/{hierarchy}"

    # Background Sync Configuration
    SYNC_ENABLED: bool = True  # Enable background sync service
    SYNC_ON_STARTUP: bool = True  # Run sync immediately on startup
    SYNC_CHARGERS_INTERVAL: int = 3600  # Charger sync interval in seconds (1 hour)
    SYNC_TELEMETRY_INTERVAL: int = 21600  # Telemetry sync interval in seconds (6 hours)
    SYNC_TELEMETRY_LIMIT: int = 1000  # Maximum telemetry records to sync per run

    # Logging Configuration
    LOG_LEVEL: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    LOG_FORMAT: str = "simple"  # simple or json
    LOG_CORRELATION_HEADER: str = "X-Correlation-ID"  # Header for correlation IDs
    ENABLE_REQUEST_LOGGING: bool = True  # Log all API requests/responses
    ENABLE_PERFORMANCE_LOGGING: bool = True  # Log timing information

    @property
    def database_url(self):
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def async_database_url(self):
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def anomaly_alert_recipients_list(self) -> list[str]:
        """Parse comma-separated recipients into a list."""
        return [
            email.strip()
            for email in self.ANOMALY_ALERT_RECIPIENTS.split(",")
            if email.strip()
        ]

    @field_validator(
        "PIONIX_DEVICE_MODEL_ENDPOINT",
        "PIONIX_TELEMETRY_ENDPOINT",
        "PIONIX_MQTT_TELEMETRY_TOPIC",
    )
    @classmethod
    def validate_endpoint_templates(cls, v: str, info: FieldValidationInfo) -> str:
        """Validate that endpoint templates contain expected placeholders."""
        required_placeholders = {
            "PIONIX_DEVICE_MODEL_ENDPOINT": ["{charger_id}"],
            "PIONIX_TELEMETRY_ENDPOINT": ["{charger_id}", "{hierarchy}"],
            "PIONIX_MQTT_TELEMETRY_TOPIC": ["{charger_id}", "{hierarchy}"],
        }

        field_name = info.field_name

        if field_name in required_placeholders:
            for placeholder in required_placeholders[field_name]:
                if placeholder not in v:
                    raise ValueError(
                        f"Field '{field_name}' template must contain {placeholder}"
                    )

        return v

    def build_mqtt_topic(self, charger_id: str, hierarchy: str) -> str:
        """
        Build MQTT topic with parameter substitution.

        Args:
            charger_id: Charger ID
            hierarchy: Telemetry hierarchy path

        Returns:
            Formatted MQTT topic string with parameters substituted

        Raises:
            ValueError: If required parameters are missing
        """
        try:
            return self.PIONIX_MQTT_TELEMETRY_TOPIC.format(
                charger_id=charger_id, hierarchy=hierarchy
            )
        except KeyError as e:
            raise ValueError(f"Missing required parameter {e} for MQTT topic template")

    @property
    def pionix_config(self) -> "PionixConfig":
        """
        Create PionixConfig instance from centralized settings.

        Returns:
            PionixConfig instance populated with environment variables
        """
        # Import here to avoid circular imports
        from ..core.client.pionix_config import PionixConfig

        return PionixConfig(
            api_key=self.PIONIX_KEY,
            user_agent=self.PIONIX_USER_AGENT,
            chargers_endpoint=self.PIONIX_CHARGERS_ENDPOINT,
            device_model_endpoint=self.PIONIX_DEVICE_MODEL_ENDPOINT,
            telemetry_endpoint=self.PIONIX_TELEMETRY_ENDPOINT,
        )

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
        # Import here to avoid circular imports
        from ..services.mqtt.config import MQTTConfig

        # Use PIONIX_KEY as fallback for MQTT_APIKEY if empty
        mqtt_api_key = self.MQTT_APIKEY or self.PIONIX_KEY

        return MQTTConfig(
            broker_host=self.MQTT_BROKER_HOST,
            broker_port=self.MQTT_BROKER_PORT,
            use_tls=self.MQTT_USE_TLS,
            client_id_prefix=self.MQTT_CLIENT_ID_PREFIX,
            mqtt_username=self.MQTT_USERNAME,
            mqtt_api_key=mqtt_api_key,
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
        )


settings = Settings()  # noqa
