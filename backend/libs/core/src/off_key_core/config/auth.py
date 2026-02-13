from functools import lru_cache

from pydantic import BaseModel, SecretStr

from .config import get_settings


class AuthSettings(BaseModel):
    """Authentication and authorization settings."""

    JWT_SECRET: SecretStr
    JWT_VERIFICATION_SECRET: SecretStr
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    SUPERUSER_MAIL: str


@lru_cache(maxsize=1)
def get_auth_settings() -> AuthSettings:
    """Return cached AuthSettings view derived from canonical Settings."""
    settings = get_settings()
    return AuthSettings(
        JWT_SECRET=settings.JWT_SECRET,
        JWT_VERIFICATION_SECRET=settings.JWT_VERIFICATION_SECRET,
        ALGORITHM=settings.ALGORITHM,
        ACCESS_TOKEN_EXPIRE_MINUTES=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        SUPERUSER_MAIL=settings.SUPERUSER_MAIL,
    )
