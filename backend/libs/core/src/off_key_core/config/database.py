from functools import lru_cache
from urllib.parse import quote

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def build_postgres_database_url(
    *,
    user: str,
    password: str,
    host: str,
    port: int,
    database: str,
    async_driver: bool = False,
) -> str:
    """Build a URL-encoded PostgreSQL DSN using the canonical off-key format."""
    scheme = "postgresql+asyncpg" if async_driver else "postgresql"
    encoded_user = quote(user, safe="")
    encoded_password = quote(password, safe="")
    encoded_database = quote(database, safe="")
    return (
        f"{scheme}://{encoded_user}:{encoded_password}@{host}:{port}/{encoded_database}"
    )


class DatabaseSettings(BaseSettings):
    """Database connection settings."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore", frozen=True)

    POSTGRES_USER: str
    POSTGRES_PASSWORD: SecretStr
    POSTGRES_DB: str
    POSTGRES_PORT: int = Field(ge=1, le=65535)
    POSTGRES_HOST: str

    @property
    def database_url(self) -> str:
        return build_postgres_database_url(
            user=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD.get_secret_value(),
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
            database=self.POSTGRES_DB,
        )

    @property
    def async_database_url(self) -> str:
        return build_postgres_database_url(
            user=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD.get_secret_value(),
            host=self.POSTGRES_HOST,
            port=self.POSTGRES_PORT,
            database=self.POSTGRES_DB,
            async_driver=True,
        )


# Cache parsed settings to avoid repeated env parsing; tests clear this explicitly.
@lru_cache(maxsize=1)
def get_database_settings() -> DatabaseSettings:
    """Return cached database settings."""
    return DatabaseSettings()
