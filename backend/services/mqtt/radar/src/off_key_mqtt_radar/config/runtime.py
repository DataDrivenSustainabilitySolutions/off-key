from functools import lru_cache

from off_key_core.config.database import DatabaseSettings
from off_key_core.config.radar import DEVELOPMENT_CHECKPOINT_SECRET
from off_key_core.config.validation import SECRETS_DIR, Environment
from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RadarDatabaseSettings(BaseSettings):
    """Runtime database settings for RADAR service internals.

    TACTIC passes RADAR_DATABASE_URL to managed workers; otherwise the shared
    POSTGRES_* settings apply, with the same rules as every other service.
    """

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    RADAR_DATABASE_URL: str | None = None

    @model_validator(mode="after")
    def validate_database_source(self) -> "RadarDatabaseSettings":
        direct_url = (self.RADAR_DATABASE_URL or "").strip()
        if direct_url:
            scheme, sep, _ = direct_url.partition("://")
            if not sep:
                raise ValueError(
                    "RADAR_DATABASE_URL must be a valid URL with an explicit scheme"
                )
            if scheme.lower() != "postgresql+asyncpg":
                raise ValueError(
                    "RADAR_DATABASE_URL must use the postgresql+asyncpg:// scheme"
                )
            return self
        try:
            DatabaseSettings()
        except ValidationError as exc:
            raise ValueError(
                "Set RADAR_DATABASE_URL or all POSTGRES_* variables "
                "(USER, PASSWORD, HOST, PORT, DB)"
            ) from exc
        return self

    @property
    def async_database_url(self) -> str:
        direct_url = (self.RADAR_DATABASE_URL or "").strip()
        return direct_url or DatabaseSettings().async_database_url


class RadarCheckpointSettings(BaseSettings):
    """Runtime checkpoint settings for RADAR service internals."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        secrets_dir=SECRETS_DIR,
    )

    SERVICE_ID: str = "default"
    RADAR_CHECKPOINT_SECRET: SecretStr = SecretStr("")
    RADAR_CHECKPOINT_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0)
    RADAR_CHECKPOINT_MAX_INTERVAL_SECONDS: float = Field(default=30.0, gt=0)
    RADAR_FATAL_PERSIST_RETRY_SECONDS: float = Field(default=5.0, gt=0, le=30)
    ENVIRONMENT: Environment = "development"

    @field_validator("SERVICE_ID")
    @classmethod
    def validate_non_empty_string(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Service id must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_checkpoint_secret_for_environment(self) -> "RadarCheckpointSettings":
        secret = self.RADAR_CHECKPOINT_SECRET.get_secret_value().strip()
        if self.ENVIRONMENT == "production" and (
            not secret or secret == DEVELOPMENT_CHECKPOINT_SECRET
        ):
            raise ValueError(
                "RADAR_CHECKPOINT_SECRET must be set when ENVIRONMENT=production"
            )
        return self

    @property
    def checkpoint_secret_bytes(self) -> bytes:
        return self.RADAR_CHECKPOINT_SECRET.get_secret_value().encode()

    @property
    def durable_checkpoint_secret_bytes(self) -> bytes:
        secret = self.checkpoint_secret_bytes
        if secret:
            return secret
        if self.ENVIRONMENT == "production":
            raise ValueError("Managed checkpoints require RADAR_CHECKPOINT_SECRET")
        return DEVELOPMENT_CHECKPOINT_SECRET.encode()


class RadarRuntimeFileSettings(BaseSettings):
    """Optional runtime file settings for RADAR service startup."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    RADAR_CONFIG_FILE: str | None = None
    ENVIRONMENT: Environment = "development"


# Cache secret-bearing DB settings once; tests reset this cache when mutating env.
@lru_cache(maxsize=1)
def get_radar_database_settings() -> RadarDatabaseSettings:
    return RadarDatabaseSettings()


# Cache checkpoint secret settings once; tests reset this cache when mutating env.
@lru_cache(maxsize=1)
def get_radar_checkpoint_settings() -> RadarCheckpointSettings:
    return RadarCheckpointSettings()


@lru_cache(maxsize=1)
def get_radar_runtime_file_settings() -> RadarRuntimeFileSettings:
    return RadarRuntimeFileSettings()


def clear_radar_runtime_settings_cache() -> None:
    get_radar_database_settings.cache_clear()
    get_radar_checkpoint_settings.cache_clear()
    get_radar_runtime_file_settings.cache_clear()
