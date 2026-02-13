from functools import lru_cache

from pydantic import BaseModel, SecretStr, model_validator

from .config import get_settings


class EmailSettings(BaseModel):
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
    ANOMALY_ALERT_RECIPIENTS: str

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
    """Return cached EmailSettings view derived from canonical Settings."""
    settings = get_settings()
    return EmailSettings(
        EMAIL_USERNAME=settings.EMAIL_USERNAME,
        EMAIL_PASSWORD=settings.EMAIL_PASSWORD,
        EMAIL_FROM=settings.EMAIL_FROM,
        FRONTEND_BASE_URL=settings.FRONTEND_BASE_URL,
        SMTP_SERVER=settings.SMTP_SERVER,
        SMTP_PORT=settings.SMTP_PORT,
        MAIL_STARTTLS=settings.MAIL_STARTTLS,
        MAIL_SSL_TLS=settings.MAIL_SSL_TLS,
        USE_CREDENTIALS=settings.USE_CREDENTIALS,
        VALIDATE_CERTS=settings.VALIDATE_CERTS,
        ANOMALY_ALERT_RECIPIENTS=settings.ANOMALY_ALERT_RECIPIENTS,
    )
