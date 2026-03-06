import pytest
from pydantic import ValidationError

from off_key_core.config.email import get_email_settings


def _set_base_email_env(monkeypatch) -> None:
    monkeypatch.setenv("EMAIL_USERNAME", "sender@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "email-secret")
    monkeypatch.setenv("EMAIL_FROM", "sender@example.com")
    monkeypatch.setenv("FRONTEND_BASE_URL", "http://localhost:5173")
    monkeypatch.setenv("SMTP_SERVER", "localhost")
    monkeypatch.setenv("SMTP_PORT", "1025")
    monkeypatch.setenv("MAIL_STARTTLS", "true")
    monkeypatch.setenv("MAIL_SSL_TLS", "false")
    monkeypatch.setenv("USE_CREDENTIALS", "true")
    monkeypatch.setenv("VALIDATE_CERTS", "false")


@pytest.fixture(autouse=True)
def clear_email_settings_cache():
    get_email_settings.cache_clear()
    yield
    get_email_settings.cache_clear()


def test_email_settings_validate_and_normalize_alert_recipients(monkeypatch):
    _set_base_email_env(monkeypatch)
    monkeypatch.setenv(
        "ANOMALY_ALERT_RECIPIENTS",
        " admin@example.com,ops@example.com  ",
    )

    email_settings = get_email_settings()

    assert email_settings.anomaly_alert_recipients_list == [
        "admin@example.com",
        "ops@example.com",
    ]


def test_email_settings_reject_invalid_alert_recipient(monkeypatch):
    _set_base_email_env(monkeypatch)
    monkeypatch.setenv("ANOMALY_ALERT_RECIPIENTS", "admin@example.com,not-an-email")

    with pytest.raises(ValidationError):
        get_email_settings()


def test_email_settings_reject_empty_alert_recipients(monkeypatch):
    _set_base_email_env(monkeypatch)
    monkeypatch.setenv("ANOMALY_ALERT_RECIPIENTS", " , ")

    with pytest.raises(ValidationError):
        get_email_settings()
