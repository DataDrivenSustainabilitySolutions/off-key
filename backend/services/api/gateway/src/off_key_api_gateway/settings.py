"""Settings only the API gateway reads."""

from functools import lru_cache
from typing import Self

from off_key_core.config.validation import SECRETS_DIR
from pydantic import EmailStr, Field, SecretStr, field_validator, model_validator
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


class DemoSettings(BaseSettings):
    """Public read-only demo: anonymous visitors browse as one viewer member."""

    model_config = SettingsConfigDict(
        secrets_dir=SECRETS_DIR, case_sensitive=True, extra="ignore", frozen=True
    )

    DEMO_MODE: bool = False
    DEMO_VIEWER_EMAIL: EmailStr | None = None
    DEMO_VIEWER_PASSWORD: SecretStr | None = None
    DEMO_GUEST_REQUESTS_PER_MINUTE: int = Field(default=240, ge=1, le=10_000)

    @field_validator("DEMO_VIEWER_EMAIL", "DEMO_VIEWER_PASSWORD", mode="before")
    @classmethod
    def unset_when_empty(cls, value):
        return None if value == "" else value

    @model_validator(mode="after")
    def viewer_account(self) -> Self:
        if self.DEMO_MODE and not (
            self.DEMO_VIEWER_EMAIL
            and self.DEMO_VIEWER_PASSWORD
            and self.DEMO_VIEWER_PASSWORD.get_secret_value()
        ):
            raise ValueError(
                "DEMO_MODE needs DEMO_VIEWER_EMAIL and DEMO_VIEWER_PASSWORD"
            )
        return self


@lru_cache(maxsize=1)
def get_demo_settings() -> DemoSettings:
    """Return cached public demo settings."""
    return DemoSettings()
