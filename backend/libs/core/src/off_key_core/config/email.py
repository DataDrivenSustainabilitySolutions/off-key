from functools import lru_cache

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmailSettings(BaseSettings):
    """Email and notification settings."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore", frozen=True)

    EMAIL_USERNAME: str
    EMAIL_PASSWORD: SecretStr
    EMAIL_FROM: str
    FRONTEND_BASE_URL: str
    SMTP_SERVER: str
    SMTP_PORT: int
    MAIL_STARTTLS: bool
    MAIL_SSL_TLS: bool
    USE_CREDENTIALS: bool
    VALIDATE_CERTS: bool
    ANOMALY_ALERT_RECIPIENTS: str = "admin@example.com"

    @model_validator(mode="after")
    def check_tls_exclusivity(self) -> "EmailSettings":
        if self.MAIL_STARTTLS and self.MAIL_SSL_TLS:
            raise ValueError("MAIL_STARTTLS and MAIL_SSL_TLS are mutually exclusive")
        return self

    @property
    def anomaly_alert_recipients_list(self) -> list[str]:
        return [
            email.strip()
            for email in self.ANOMALY_ALERT_RECIPIENTS.split(",")
            if email.strip()
        ]


@lru_cache(maxsize=1)
def get_email_settings() -> EmailSettings:
    """Return cached email settings."""
    return EmailSettings()
