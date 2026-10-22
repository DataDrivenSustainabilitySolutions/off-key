from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from off_key_core.config.validation import SECRETS_DIR


class ServiceAuthSettings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=True,
        extra="ignore",
        secrets_dir=SECRETS_DIR,
    )

    INTERNAL_API_SECRET: SecretStr = Field(min_length=32)


@lru_cache(maxsize=1)
def get_service_auth_settings() -> ServiceAuthSettings:
    return ServiceAuthSettings()
