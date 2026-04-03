from functools import lru_cache

from off_key_core.config.database import build_postgres_database_url
from off_key_core.config.validation import validate_environment as _validate_environment
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RadarDatabaseSettings(BaseSettings):
    """Runtime database settings for RADAR service internals."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    RADAR_DATABASE_URL: str | None = None
    POSTGRES_USER: str | None = None
    POSTGRES_PASSWORD: SecretStr | None = None
    POSTGRES_HOST: str | None = None
    POSTGRES_PORT: str | None = None
    POSTGRES_DB: str | None = None

    @staticmethod
    def _validate_direct_database_url(url: str) -> None:
        scheme, sep, _ = url.partition("://")
        if not sep:
            raise ValueError(
                "RADAR_DATABASE_URL must be a valid URL with an explicit scheme"
            )
        if scheme.lower() != "postgresql+asyncpg":
            raise ValueError(
                "RADAR_DATABASE_URL must use the postgresql+asyncpg:// scheme"
            )

    @staticmethod
    def _parse_port(value: str | None, env_name: str) -> int:
        if value is None:
            raise ValueError(f"{env_name} must be set")
        normalized = value.strip()
        try:
            port = int(normalized)
        except ValueError as exc:
            raise ValueError(
                f"{env_name} must be an integer between 1 and 65535"
            ) from exc
        if not (1 <= port <= 65535):
            raise ValueError(f"{env_name} must be an integer between 1 and 65535")
        return port

    @model_validator(mode="after")
    def validate_database_source(self) -> "RadarDatabaseSettings":
        direct_url = (self.RADAR_DATABASE_URL or "").strip()
        if direct_url:
            self._validate_direct_database_url(direct_url)
            return self

        user = (self.POSTGRES_USER or "").strip()
        password = (
            self.POSTGRES_PASSWORD.get_secret_value() if self.POSTGRES_PASSWORD else ""
        )
        host = (self.POSTGRES_HOST or "").strip()
        port = (self.POSTGRES_PORT or "").strip()
        database = (self.POSTGRES_DB or "").strip()

        if not (user and password and host and port and database):
            raise ValueError(
                "Set RADAR_DATABASE_URL or all POSTGRES_* variables "
                "(USER, PASSWORD, HOST, PORT, DB)"
            )
        self._parse_port(port, "POSTGRES_PORT")
        return self

    @property
    def async_database_url(self) -> str:
        direct_url = (self.RADAR_DATABASE_URL or "").strip()
        if direct_url:
            return direct_url
        password = (
            self.POSTGRES_PASSWORD.get_secret_value() if self.POSTGRES_PASSWORD else ""
        )
        postgres_port = self._parse_port(self.POSTGRES_PORT, "POSTGRES_PORT")
        postgres_user = (self.POSTGRES_USER or "").strip()
        postgres_host = (self.POSTGRES_HOST or "").strip()
        postgres_db = (self.POSTGRES_DB or "").strip()
        return build_postgres_database_url(
            user=postgres_user,
            password=password,
            host=postgres_host,
            port=postgres_port,
            database=postgres_db,
            async_driver=True,
        )


class RadarTacticClientSettings(BaseSettings):
    """Runtime TACTIC connectivity settings for RADAR service internals."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    RADAR_TACTIC_BASE_URL: str | None = None
    TACTIC_SERVICE_BASE_URL: str | None = None
    RADAR_TACTIC_SERVICE_HOST: str | None = None
    TACTIC_SERVICE_HOST: str = "tactic-middleware"
    RADAR_TACTIC_SERVICE_PORT: str | None = None
    TACTIC_SERVICE_PORT: str = "8000"
    RADAR_TACTIC_MODEL_REGISTRY_CACHE_TTL_SECONDS: float | None = Field(
        default=None, gt=0
    )
    TACTIC_MODEL_REGISTRY_CACHE_TTL_SECONDS: float = Field(default=60.0, gt=0)

    @staticmethod
    def _normalize_base_url(value: str | None) -> str | None:
        if not value:
            return None
        return value.strip().rstrip("/")

    @staticmethod
    def _parse_port(value: str | None, env_name: str) -> int:
        if value is None:
            raise ValueError(f"{env_name} must be set")
        normalized = value.strip()
        try:
            port = int(normalized)
        except ValueError as exc:
            raise ValueError(
                f"{env_name} must be an integer between 1 and 65535"
            ) from exc
        if not (1 <= port <= 65535):
            raise ValueError(f"{env_name} must be an integer between 1 and 65535")
        return port

    @property
    def base_url(self) -> str:
        configured = self._normalize_base_url(self.RADAR_TACTIC_BASE_URL)
        if configured:
            return configured
        fallback = self._normalize_base_url(self.TACTIC_SERVICE_BASE_URL)
        if fallback:
            return fallback

        host = (self.RADAR_TACTIC_SERVICE_HOST or "").strip() or (
            self.TACTIC_SERVICE_HOST.strip()
        )
        radar_port = (self.RADAR_TACTIC_SERVICE_PORT or "").strip()
        if radar_port:
            port = self._parse_port(radar_port, "RADAR_TACTIC_SERVICE_PORT")
        else:
            port = self._parse_port(self.TACTIC_SERVICE_PORT, "TACTIC_SERVICE_PORT")

        return f"http://{host}:{port}"

    @property
    def cache_ttl_seconds(self) -> float:
        return (
            self.RADAR_TACTIC_MODEL_REGISTRY_CACHE_TTL_SECONDS
            or self.TACTIC_MODEL_REGISTRY_CACHE_TTL_SECONDS
        )


class RadarCheckpointSettings(BaseSettings):
    """Runtime checkpoint settings for RADAR service internals."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    RADAR_CHECKPOINT_DIR: str = "checkpoints"
    SERVICE_ID: str = "default"
    RADAR_CHECKPOINT_SECRET: SecretStr = SecretStr("")
    ENVIRONMENT: str = "development"

    @field_validator("RADAR_CHECKPOINT_DIR", "SERVICE_ID")
    @classmethod
    def validate_non_empty_string(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Checkpoint directory and service id must not be empty")
        return normalized

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        return _validate_environment(value)

    @model_validator(mode="after")
    def validate_checkpoint_secret_for_environment(self) -> "RadarCheckpointSettings":
        secret = self.RADAR_CHECKPOINT_SECRET.get_secret_value().strip()
        if self.ENVIRONMENT == "production" and not secret:
            raise ValueError(
                "RADAR_CHECKPOINT_SECRET must be set when ENVIRONMENT=production"
            )
        return self

    @property
    def checkpoint_secret_bytes(self) -> bytes:
        return self.RADAR_CHECKPOINT_SECRET.get_secret_value().encode()


class RadarRuntimeFileSettings(BaseSettings):
    """Optional runtime file settings for RADAR service startup."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    RADAR_CONFIG_FILE: str | None = None
    ENVIRONMENT: str = "development"

    @field_validator("ENVIRONMENT")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        return _validate_environment(value)


# Cache secret-bearing DB settings once; tests reset this cache when mutating env.
@lru_cache(maxsize=1)
def get_radar_database_settings() -> RadarDatabaseSettings:
    return RadarDatabaseSettings()


@lru_cache(maxsize=1)
def get_radar_tactic_client_settings() -> RadarTacticClientSettings:
    return RadarTacticClientSettings()


# Cache checkpoint secret settings once; tests reset this cache when mutating env.
@lru_cache(maxsize=1)
def get_radar_checkpoint_settings() -> RadarCheckpointSettings:
    return RadarCheckpointSettings()


@lru_cache(maxsize=1)
def get_radar_runtime_file_settings() -> RadarRuntimeFileSettings:
    return RadarRuntimeFileSettings()


def clear_radar_runtime_settings_cache() -> None:
    get_radar_database_settings.cache_clear()
    get_radar_tactic_client_settings.cache_clear()
    get_radar_checkpoint_settings.cache_clear()
    get_radar_runtime_file_settings.cache_clear()
