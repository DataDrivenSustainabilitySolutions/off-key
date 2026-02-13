from functools import lru_cache
from urllib.parse import quote

from pydantic import BaseModel, SecretStr

from .config import get_settings


class DatabaseSettings(BaseModel):
    """Database connection settings."""

    POSTGRES_USER: str
    POSTGRES_PASSWORD: SecretStr
    POSTGRES_DB: str
    POSTGRES_PORT: str
    POSTGRES_HOST: str

    @property
    def database_url(self) -> str:
        user = quote(self.POSTGRES_USER, safe="")
        password = quote(self.POSTGRES_PASSWORD.get_secret_value(), safe="")
        return (
            f"postgresql://{user}:{password}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def async_database_url(self) -> str:
        user = quote(self.POSTGRES_USER, safe="")
        password = quote(self.POSTGRES_PASSWORD.get_secret_value(), safe="")
        return (
            f"postgresql+asyncpg://{user}:{password}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache(maxsize=1)
def get_database_settings() -> DatabaseSettings:
    """Return cached DatabaseSettings view derived from canonical Settings."""
    settings = get_settings()
    return DatabaseSettings(
        POSTGRES_USER=settings.POSTGRES_USER,
        POSTGRES_PASSWORD=settings.POSTGRES_PASSWORD,
        POSTGRES_DB=settings.POSTGRES_DB,
        POSTGRES_PORT=settings.POSTGRES_PORT,
        POSTGRES_HOST=settings.POSTGRES_HOST,
    )
