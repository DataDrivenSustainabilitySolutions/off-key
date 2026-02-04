from functools import lru_cache

from pydantic_settings import BaseSettings


class AuthSettings(BaseSettings):
    """Authentication and authorization settings."""

    JWT_SECRET: str
    JWT_VERIFICATION_SECRET: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    SUPERUSER_MAIL: str


@lru_cache(maxsize=1)
def get_auth_settings() -> AuthSettings:
    """Return cached AuthSettings instance."""
    return AuthSettings()
