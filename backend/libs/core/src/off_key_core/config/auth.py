from functools import lru_cache

from pydantic import EmailStr, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    """Authentication and authorization settings."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore", frozen=True)

    JWT_SECRET: SecretStr
    JWT_VERIFICATION_SECRET: SecretStr
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    SUPERUSER_MAIL: EmailStr


@lru_cache(maxsize=1)
def get_auth_settings() -> AuthSettings:
    """Return cached auth settings."""
    return AuthSettings()
