from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceAuthSettings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        secrets_dir="/run/secrets" if Path("/run/secrets").is_dir() else None,
    )

    INTERNAL_API_SECRET: SecretStr = Field(min_length=32)


@lru_cache(maxsize=1)
def get_service_auth_settings() -> ServiceAuthSettings:
    return ServiceAuthSettings()
