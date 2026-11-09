"""Settings only the API gateway reads."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Gateway application settings: name and browser origins."""

    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        frozen=True,
    )

    APP_NAME: str
    CORS_ALLOWED_ORIGINS: tuple[str, ...] = (
        "http://localhost:8000",
        "http://localhost:5173",
    )


@lru_cache(maxsize=1)
def get_app_settings() -> AppSettings:
    """Return cached app-level settings."""
    return AppSettings()


class ServiceEndpointsSettings(BaseSettings):
    """Where the gateway reaches TACTIC."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore", frozen=True)

    TACTIC_SERVICE_SCHEME: str = "http"
    TACTIC_SERVICE_HOST: str = "middleware_tactic"
    TACTIC_SERVICE_PORT: int = Field(default=8000, ge=1, le=65535)
    TACTIC_SERVICE_REQUEST_TIMEOUT_SECONDS: float = Field(default=180.0, gt=0)

    @property
    def tactic_service_base_url(self) -> str:
        return (
            f"{self.TACTIC_SERVICE_SCHEME}://"
            f"{self.TACTIC_SERVICE_HOST}:{self.TACTIC_SERVICE_PORT}"
        )

    @field_validator("TACTIC_SERVICE_SCHEME")
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
