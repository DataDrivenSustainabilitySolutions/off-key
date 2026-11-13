"""Explicit public-demo opt-in and server-only viewer credentials."""

from pydantic import EmailStr, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from off_key_core.config.validation import SECRETS_DIR


class DemoSettings(BaseSettings):
    """Explicit opt-in, only on an isolated installation containing public data."""

    model_config = SettingsConfigDict(
        case_sensitive=True, extra="ignore", frozen=True, secrets_dir=SECRETS_DIR
    )
    DEMO_MODE: bool = False
    DEMO_VIEWER_EMAIL: EmailStr | None = None
    DEMO_VIEWER_PASSWORD: SecretStr | None = None
    DEMO_GUEST_REQUESTS_PER_MINUTE: int = Field(default=600, ge=10, le=6000)

    @model_validator(mode="after")
    def configured_viewer(self):
        if self.DEMO_MODE and (
            not self.DEMO_VIEWER_EMAIL
            or not self.DEMO_VIEWER_PASSWORD
            or not 32
            <= len(self.DEMO_VIEWER_PASSWORD.get_secret_value().encode())
            <= 72
        ):
            raise ValueError(
                "Demo mode needs DEMO_VIEWER_EMAIL and a dedicated "
                "32-72 byte DEMO_VIEWER_PASSWORD"
            )
        return self
