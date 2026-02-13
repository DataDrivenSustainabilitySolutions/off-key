from pydantic_settings import BaseSettings
from pydantic import (
    AliasChoices,
    Field,
    field_validator,
    ValidationInfo,
    BaseModel,
    SecretStr,
)
from dotenv import find_dotenv, load_dotenv
from urllib.parse import quote

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
    JWT_SECRET: SecretStr
    JWT_VERIFICATION_SECRET: SecretStr
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    SUPERUSER_MAIL: str

    # Email Service Configuration
    EMAIL_USERNAME: str
    EMAIL_PASSWORD: SecretStr
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
    POSTGRES_PASSWORD: SecretStr
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
    TELEMETRY_RETENTION_DAYS: int = Field(
        14,
        validation_alias=AliasChoices(
            "TELEMETRY_RETENTION_DAYS", "SYNC_RETENTION_DAYS"
        ),
    )

    # DB Sync Service Configuration
    SYNC_SERVICE_SCHEME: str = "http"
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
    TACTIC_SERVICE_SCHEME: str = "http"
    TACTIC_SERVICE_HOST: str = "middleware_tactic"
    TACTIC_SERVICE_PORT: int = 8000
    TACTIC_MODEL_REGISTRY_CACHE_TTL_SECONDS: float = 60.0

    @property
    def database_url(self):
        user = quote(self.POSTGRES_USER, safe="")
        password = quote(self.POSTGRES_PASSWORD.get_secret_value(), safe="")
        return (
            f"postgresql://{user}:{password}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def async_database_url(self):
        user = quote(self.POSTGRES_USER, safe="")
        password = quote(self.POSTGRES_PASSWORD.get_secret_value(), safe="")
        return (
            f"postgresql+asyncpg://{user}:{password}"
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
    def validate_endpoint_templates(cls, v: str, info: ValidationInfo) -> str:
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
        return (
            f"{self.TACTIC_SERVICE_SCHEME}://"
            f"{self.TACTIC_SERVICE_HOST}:{self.TACTIC_SERVICE_PORT}"
        )

    @field_validator("TACTIC_MODEL_REGISTRY_CACHE_TTL_SECONDS")
    @classmethod
    def validate_tactic_model_registry_cache_ttl(cls, v: float) -> float:
        """Ensure cache TTL is positive to avoid stale-forever/always-refetch bugs."""
        if v <= 0:
            raise ValueError("TACTIC_MODEL_REGISTRY_CACHE_TTL_SECONDS must be > 0")
        return v

    @field_validator("SYNC_SERVICE_SCHEME", "TACTIC_SERVICE_SCHEME")
    @classmethod
    def validate_service_scheme(cls, value: str) -> str:
        normalized = value.lower().strip()
        if normalized not in {"http", "https"}:
            raise ValueError("Service scheme must be either 'http' or 'https'")
        return normalized

    @field_validator("TELEMETRY_RETENTION_DAYS")
    @classmethod
    def validate_retention_days(cls, v: int) -> int:
        """Ensure telemetry retention stays within a reasonable window."""
        if not 1 <= v <= 365:
            raise ValueError("Telemetry retention days must be between 1 and 365")
        return v

    @property
    def db_sync_service_url(self) -> str:
        """
        Build the base URL used to reach the DB Sync service.
        """
        return f"{self.SYNC_SERVICE_SCHEME}://{self.SYNC_HOSTNAME}:{self.SYNC_API_PORT}"

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


# Cached settings instance to avoid recreating multiple times
_settings_instance: Settings | None = None


def get_settings() -> Settings:
    """Get cached Settings instance."""
    global _settings_instance
    if _settings_instance is None:
        _settings_instance = Settings()
    return _settings_instance


def reset_settings_cache() -> None:
    """Clear cached Settings instance."""
    global _settings_instance
    _settings_instance = None


def get_telemetry_settings():
    """Compatibility wrapper for telemetry settings getter."""
    from .telemetry import get_telemetry_settings as _get_telemetry_settings

    return _get_telemetry_settings()
