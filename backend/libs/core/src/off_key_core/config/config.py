import threading
from typing import cast

from pydantic_settings import BaseSettings
from pydantic import (
    AliasChoices,
    Field,
    field_validator,
    FieldValidationInfo,
    BaseModel,
    SecretStr,
)
from dotenv import find_dotenv, load_dotenv

# Load default ".env" file from upper project tree
load_dotenv()

# Override with dev.env values if present
dev_env = find_dotenv("dev.env")
if dev_env:
    load_dotenv(dev_env, override=True)


class PionixConfig(BaseModel):
    """
    Configuration for Pionix API client.

    This is a pure data model containing only configuration values.
    """

    # API Connection
    base_url: str = "https://cloud.pionix.com/api"
    api_key: SecretStr
    user_agent: str

    # Endpoint Templates
    chargers_endpoint: str
    device_model_endpoint: str
    telemetry_endpoint: str

    class Config:
        # Prevent extra fields
        extra = "forbid"


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
    PIONIX_KEY: SecretStr
    PIONIX_USER_AGENT: str

    # Pionix API Endpoint Templates
    PIONIX_CHARGERS_ENDPOINT: str = "chargers"
    PIONIX_DEVICE_MODEL_ENDPOINT: str = "chargers/{charger_id}/deviceModel"
    PIONIX_TELEMETRY_ENDPOINT: str = "chargers/{charger_id}/telemetry/{hierarchy}"

    # Alerting Configuration
    ANOMALY_ALERT_RECIPIENTS: str = "admin@example.com"  # Comma-separated list

    # MQTT Topic Templates
    PIONIX_MQTT_TELEMETRY_TOPIC: str = "charger/{charger_id}/live-telemetry/{hierarchy}"

    # Background Sync Configuration
    SYNC_ENABLED: bool = True  # Enable background sync service
    SYNC_ON_STARTUP: bool = True  # Run sync immediately on startup
    SYNC_CHARGERS_INTERVAL: int = 3600  # Charger sync interval in seconds (1 hour)
    SYNC_TELEMETRY_INTERVAL: int = 21600  # Telemetry sync interval in seconds (6 hours)
    SYNC_TELEMETRY_LIMIT: int = 1000  # Maximum telemetry records to sync per run

    # DB Sync Service Configuration
    SYNC_HOSTNAME: str = "db-sync"  # Hostname for db-sync service
    SYNC_API_PORT: int = 8009  # API port for db-sync service

    # Logging Configuration
    LOG_LEVEL: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    LOG_FORMAT: str = "simple"  # simple or json
    LOG_CORRELATION_HEADER: str = "X-Correlation-ID"  # Header for correlation IDs
    ENABLE_REQUEST_LOGGING: bool = True  # Log all API requests/responses
    ENABLE_PERFORMANCE_LOGGING: bool = True  # Log timing information

    # CORS Configuration
    CORS_ALLOWED_ORIGINS: list[str] = [
        "http://localhost:8000",
        "http://localhost:5173",
    ]  # List of allowed origins for CORS

    # Middleware TACTIC Service
    TACTIC_SERVICE_HOST: str = "middleware_tactic"
    TACTIC_SERVICE_PORT: int = 8000

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
    def tactic_service_base_url(self) -> str:
        """
        Build the base URL used to reach the middleware TACTIC service.
        """
        return f"http://{self.TACTIC_SERVICE_HOST}:{self.TACTIC_SERVICE_PORT}"

    @property
    def db_sync_service_url(self) -> str:
        """
        Build the base URL used to reach the DB Sync service.
        """
        return f"http://{self.SYNC_HOSTNAME}:{self.SYNC_API_PORT}"

    @property
    def pionix_config(self) -> "PionixConfig":
        """
        Create PionixConfig instance from centralized settings.

        Returns:
            PionixConfig instance populated with environment variables
        """

        return PionixConfig(
            api_key=self.PIONIX_KEY,
            user_agent=self.PIONIX_USER_AGENT,
            chargers_endpoint=self.PIONIX_CHARGERS_ENDPOINT,
            device_model_endpoint=self.PIONIX_DEVICE_MODEL_ENDPOINT,
            telemetry_endpoint=self.PIONIX_TELEMETRY_ENDPOINT,
        )


# Lazy singleton pattern - avoid side effects on import
# This allows modules like logs.py to be imported without requiring all env vars
_settings: Settings | None = None
_settings_lock = threading.Lock()


def get_settings() -> Settings:
    """Get or create Settings singleton (thread-safe).

    Uses double-check locking pattern to ensure thread-safe initialization
    while avoiding lock overhead on subsequent calls.

    Only instantiates when env vars are available.
    """
    global _settings
    if _settings is None:
        with _settings_lock:
            # Double-check after acquiring lock
            if _settings is None:
                _settings = Settings()
    return _settings


class _SettingsProxy:
    """Proxy that lazily creates Settings on first attribute access.

    This proxy provides backward compatibility while deferring Settings
    instantiation until first use. Type checkers see this as Settings
    via the module-level cast.
    """

    def __getattr__(self, name: str):
        return getattr(get_settings(), name)

    def __setattr__(self, name: str, value):
        setattr(get_settings(), name, value)

    def __repr__(self) -> str:
        return repr(get_settings())


# Cast to Settings for type checker compatibility
# At runtime this is a _SettingsProxy that defers to get_settings()
settings: Settings = cast(Settings, _SettingsProxy())


class TelemetrySettings(BaseSettings):
    """
    Configuration for telemetry data retention and related limits.

    This lives in the core package so shared services use the same validated
    values rather than each implementing their own parsing logic.
    """

    TELEMETRY_RETENTION_DAYS: int = Field(
        14,
        validation_alias=AliasChoices(
            "TELEMETRY_RETENTION_DAYS", "SYNC_RETENTION_DAYS"
        ),
    )

    @field_validator("TELEMETRY_RETENTION_DAYS")
    @classmethod
    def validate_retention_days(cls, v: int) -> int:
        """Ensure telemetry retention stays within a reasonable window."""
        if not 1 <= v <= 365:
            raise ValueError("Telemetry retention days must be between 1 and 365")
        return v

    @property
    def retention_days(self) -> int:
        """Expose a friendlier name used by services."""
        return self.TELEMETRY_RETENTION_DAYS


telemetry_settings = TelemetrySettings()
