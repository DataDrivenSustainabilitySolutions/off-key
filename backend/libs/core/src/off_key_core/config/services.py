from functools import lru_cache

from pydantic_settings import BaseSettings


class ServiceEndpointsSettings(BaseSettings):
    """Service discovery endpoints shared across services."""

    SYNC_HOSTNAME: str = "db-sync"
    SYNC_API_PORT: int = 8009

    TACTIC_SERVICE_HOST: str = "middleware_tactic"
    TACTIC_SERVICE_PORT: int = 8000

    @property
    def db_sync_service_url(self) -> str:
        return f"http://{self.SYNC_HOSTNAME}:{self.SYNC_API_PORT}"

    @property
    def tactic_service_base_url(self) -> str:
        return f"http://{self.TACTIC_SERVICE_HOST}:{self.TACTIC_SERVICE_PORT}"


@lru_cache(maxsize=1)
def get_service_endpoints_settings() -> ServiceEndpointsSettings:
    """Return cached ServiceEndpointsSettings instance."""
    return ServiceEndpointsSettings()
