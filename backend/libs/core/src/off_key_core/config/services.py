from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .config import get_settings


class ServiceEndpointsSettings(BaseModel):
    """Service endpoint settings shared across services."""

    model_config = ConfigDict(frozen=True)

    SYNC_SERVICE_SCHEME: str = "http"
    SYNC_HOSTNAME: str
    SYNC_API_PORT: int = Field(ge=1, le=65535)
    TACTIC_SERVICE_SCHEME: str = "http"
    TACTIC_SERVICE_HOST: str
    TACTIC_SERVICE_PORT: int = Field(ge=1, le=65535)
    TACTIC_MODEL_REGISTRY_CACHE_TTL_SECONDS: float

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

    @field_validator("TACTIC_MODEL_REGISTRY_CACHE_TTL_SECONDS")
    @classmethod
    def validate_tactic_model_registry_cache_ttl(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("TACTIC_MODEL_REGISTRY_CACHE_TTL_SECONDS must be > 0")
        return value


@lru_cache(maxsize=1)
def get_service_endpoints_settings() -> ServiceEndpointsSettings:
    """Return cached service endpoint settings derived from canonical Settings."""
    settings = get_settings()
    return ServiceEndpointsSettings(
        SYNC_SERVICE_SCHEME=settings.SYNC_SERVICE_SCHEME,
        SYNC_HOSTNAME=settings.SYNC_HOSTNAME,
        SYNC_API_PORT=settings.SYNC_API_PORT,
        TACTIC_SERVICE_SCHEME=settings.TACTIC_SERVICE_SCHEME,
        TACTIC_SERVICE_HOST=settings.TACTIC_SERVICE_HOST,
        TACTIC_SERVICE_PORT=settings.TACTIC_SERVICE_PORT,
        TACTIC_MODEL_REGISTRY_CACHE_TTL_SECONDS=(
            settings.TACTIC_MODEL_REGISTRY_CACHE_TTL_SECONDS
        ),
    )


def _clear_service_endpoints_settings_cache() -> None:
    """Clear cached service endpoint settings.

    For coordinated runtime cache reset (including canonical ``get_settings()``),
    use ``off_key_core.config.reset_runtime_caches_for_tests``.
    """
    get_service_endpoints_settings.cache_clear()
