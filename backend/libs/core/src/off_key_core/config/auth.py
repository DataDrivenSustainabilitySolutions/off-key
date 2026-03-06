from functools import lru_cache

from pydantic import EmailStr, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ALLOWED_JWT_ALGORITHMS = frozenset({"HS256", "HS384", "HS512"})
_MIN_SECRET_LENGTH = 32
_MAX_ACCESS_TOKEN_EXPIRE_MINUTES = 1440


class AuthSettings(BaseSettings):
    """Authentication and authorization settings."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore", frozen=True)

    JWT_SECRET: SecretStr
    JWT_VERIFICATION_SECRET: SecretStr
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    SUPERUSER_MAIL: EmailStr
    JWT_ISSUER: str = "off-key-api-gateway"
    JWT_AUDIENCE: str = "off-key-api-gateway-users"
    JWT_CLOCK_SKEW_SECONDS: int = 30

    @field_validator("JWT_SECRET", "JWT_VERIFICATION_SECRET")
    @classmethod
    def validate_jwt_secret_strength(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if secret != secret.strip():
            raise ValueError(
                "JWT secrets must not contain leading or trailing whitespace"
            )
        if len(secret) < _MIN_SECRET_LENGTH:
            raise ValueError(
                f"JWT secrets must be at least {_MIN_SECRET_LENGTH} characters long"
            )
        return value

    @field_validator("ALGORITHM")
    @classmethod
    def validate_algorithm(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in _ALLOWED_JWT_ALGORITHMS:
            allowed = ", ".join(sorted(_ALLOWED_JWT_ALGORITHMS))
            raise ValueError(f"ALGORITHM must be one of: {allowed}")
        return normalized

    @field_validator("ACCESS_TOKEN_EXPIRE_MINUTES")
    @classmethod
    def validate_access_token_expire_minutes(cls, value: int) -> int:
        if not 1 <= value <= _MAX_ACCESS_TOKEN_EXPIRE_MINUTES:
            raise ValueError(
                "ACCESS_TOKEN_EXPIRE_MINUTES must be between 1 and "
                f"{_MAX_ACCESS_TOKEN_EXPIRE_MINUTES}"
            )
        return value

    @field_validator("JWT_ISSUER", "JWT_AUDIENCE")
    @classmethod
    def validate_non_empty_token_scope(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("JWT_ISSUER and JWT_AUDIENCE must not be empty")
        return normalized

    @field_validator("JWT_CLOCK_SKEW_SECONDS")
    @classmethod
    def validate_clock_skew_seconds(cls, value: int) -> int:
        if not 0 <= value <= 300:
            raise ValueError("JWT_CLOCK_SKEW_SECONDS must be between 0 and 300")
        return value

    @model_validator(mode="after")
    def validate_distinct_jwt_secrets(self) -> "AuthSettings":
        if (
            self.JWT_SECRET.get_secret_value()
            == self.JWT_VERIFICATION_SECRET.get_secret_value()
        ):
            raise ValueError("JWT_SECRET and JWT_VERIFICATION_SECRET must differ")
        return self


@lru_cache(maxsize=1)
def get_auth_settings() -> AuthSettings:
    """Return cached auth settings."""
    return AuthSettings()
