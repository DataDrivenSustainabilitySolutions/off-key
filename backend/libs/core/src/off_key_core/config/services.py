from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceEndpointsSettings(BaseSettings):
    """Service endpoint settings shared across services."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore", frozen=True)

    SYNC_SERVICE_SCHEME: str = "http"
    SYNC_HOSTNAME: str = "db-sync"
    SYNC_API_PORT: int = Field(default=8009, ge=1, le=65535)
    TACTIC_SERVICE_SCHEME: str = "http"
    TACTIC_SERVICE_HOST: str = "middleware_tactic"
    TACTIC_SERVICE_PORT: int = Field(default=8000, ge=1, le=65535)
    TACTIC_MODEL_REGISTRY_CACHE_TTL_SECONDS: float = Field(default=60.0, gt=0)

    @property
    def db_sync_service_url(self) -> str:
        return f"{self.SYNC_SERVICE_SCHEME}://{self.SYNC_HOSTNAME}:{self.SYNC_API_PORT}"

    @property
    def tactic_service_base_url(self) -> str:
        return (
            f"{self.TACTIC_SERVICE_SCHEME}://"
            f"{self.TACTIC_SERVICE_HOST}:{self.TACTIC_SERVICE_PORT}"
        )

    @field_validator("SYNC_SERVICE_SCHEME", "TACTIC_SERVICE_SCHEME")
    @classmethod
    def validate_service_scheme(cls, value: str) -> str:
        normalized = value.lower().strip()
        if normalized not in {"http", "https"}:
            raise ValueError("Service scheme must be either 'http' or 'https'")
        return normalized


@lru_cache(maxsize=1)
def get_service_endpoints_settings() -> ServiceEndpointsSettings:
    """Return cached service endpoint settings."""
    return ServiceEndpointsSettings()


def _clear_service_endpoints_settings_cache() -> None:
    """Clear cached service endpoint settings."""
    get_service_endpoints_settings.cache_clear()
