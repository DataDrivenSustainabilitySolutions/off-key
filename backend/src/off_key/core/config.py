from pydantic_settings import BaseSettings
from dotenv import find_dotenv, load_dotenv

# Load default ".env" file from upper project tree
load_dotenv()

# Override with dev.env values if present
dev_env = find_dotenv("dev.env")
if dev_env:
    load_dotenv(dev_env, override=True)


class Settings(BaseSettings):

    APP_NAME: str
    DEBUG: bool = False  # Set to True in development for SQL logging

    JWT_SECRET: str
    JWT_VERIFICATION_SECRET: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    SUPERUSER_MAIL: str

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

    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_PORT: str
    POSTGRES_HOST: str  # 'postgres' if connecting from another container

    PIONIX_KEY: str
    PIONIX_USER_AGENT: str

    ANOMALY_ALERT_RECIPIENTS: str = "admin@example.com"  # Comma-separated list

    # MQTT Configuration
    MQTT_TELEMETRY_ENABLED: bool = True  # Enable MQTT telemetry service
    MQTT_HEALTH_CHECK_INTERVAL: int = 30  # Health check interval in seconds
    MQTT_BATCH_SIZE: int = 100  # Database batch size for MQTT messages
    MQTT_RECONNECT_DELAY: int = 5  # Reconnection delay in seconds

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


settings = Settings()  # noqa
