from unittest.mock import AsyncMock

import pytest
from off_key_core.config.email import get_email_settings
from off_key_core.utils import mail
from pydantic import ValidationError

from tests.support.env import EMAIL_ENVIRONMENT, set_environment


@pytest.fixture(autouse=True)
def clear_mail_caches():
    mail.reset_mail_runtime_caches()
    yield
    mail.reset_mail_runtime_caches()


def test_email_settings_validate_and_normalize_alert_recipients(monkeypatch):
    set_environment(monkeypatch, EMAIL_ENVIRONMENT)
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
    set_environment(monkeypatch, EMAIL_ENVIRONMENT)
    monkeypatch.setenv("ANOMALY_ALERT_RECIPIENTS", "admin@example.com,not-an-email")

    with pytest.raises(ValidationError):
        get_email_settings()


def test_email_settings_reject_empty_alert_recipients(monkeypatch):
    set_environment(monkeypatch, EMAIL_ENVIRONMENT)
    monkeypatch.setenv("ANOMALY_ALERT_RECIPIENTS", " , ")

    with pytest.raises(ValidationError):
        get_email_settings()


@pytest.mark.asyncio
async def test_resend_transport_delivers_invitation_and_reset_links(monkeypatch):
    set_environment(monkeypatch, EMAIL_ENVIRONMENT)
    for key, value in {
        "EMAIL_USERNAME": "resend",
        "EMAIL_PASSWORD": "re_test_key_not_a_secret",
        "EMAIL_FROM": "no-reply@aberration.app",
        "SMTP_SERVER": "smtp.resend.com",
        "SMTP_PORT": "587",
        "VALIDATE_CERTS": "true",
        "FRONTEND_BASE_URL": "https://dashboard.aberration.app",
        "ANOMALY_ALERT_RECIPIENTS": "admin@example.com",
    }.items():
        monkeypatch.setenv(key, value)
    transport = mail.get_mail_config()
    assert transport.MAIL_SERVER == "smtp.resend.com"
    assert transport.MAIL_PORT == 587
    assert transport.MAIL_USERNAME == "resend"
    assert transport.MAIL_PASSWORD.get_secret_value() == "re_test_key_not_a_secret"
    assert transport.MAIL_FROM == "no-reply@aberration.app"
    assert transport.MAIL_STARTTLS and not transport.MAIL_SSL_TLS
    assert transport.USE_CREDENTIALS and transport.VALIDATE_CERTS
    send = AsyncMock()
    monkeypatch.setattr(mail.FastMail, "send_message", send)
    await mail.send_invitation_email("member@example.com", "invitation-token")
    await mail.send_password_reset_email("member@example.com", "reset-token")
    invitation, reset = [call.args[0] for call in send.await_args_list]
    assert invitation.recipients == reset.recipients
    assert [recipient.email for recipient in invitation.recipients] == [
        "member@example.com"
    ]
    assert (
        "https://dashboard.aberration.app/register#token=invitation-token"
        in invitation.body
    )
    assert (
        "https://dashboard.aberration.app/reset-password#token=reset-token"
        in reset.body
    )
