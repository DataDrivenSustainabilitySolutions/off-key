from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings


class EmailSettings(BaseSettings):
    """Email and notification settings."""

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

    @property
    def anomaly_alert_recipients_list(self) -> list[str]:
        """Parse comma-separated recipients into a list."""
        return [
            email.strip()
            for email in self.ANOMALY_ALERT_RECIPIENTS.split(",")
            if email.strip()
        ]


@lru_cache(maxsize=1)
def get_email_settings() -> EmailSettings:
    """Return cached EmailSettings instance."""
    return EmailSettings()
