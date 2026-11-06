import time
from functools import lru_cache

from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType

from ..config.email import get_email_settings
from ..config.logs import (
    log_performance,
    log_security_event,
    logger,
    redact_email,
)
from ..schemas.alarms import Alarm


@lru_cache(maxsize=1)
def get_mail_config() -> ConnectionConfig:
    """Create and cache FastMail connection config."""
    settings = get_email_settings()
    return ConnectionConfig(
        MAIL_USERNAME=settings.EMAIL_USERNAME,
        MAIL_PASSWORD=settings.EMAIL_PASSWORD.get_secret_value(),
        MAIL_FROM=settings.EMAIL_FROM,
        MAIL_PORT=settings.SMTP_PORT,
        MAIL_SERVER=settings.SMTP_SERVER,
        MAIL_SSL_TLS=settings.MAIL_SSL_TLS,
        MAIL_STARTTLS=settings.MAIL_STARTTLS,
        USE_CREDENTIALS=settings.USE_CREDENTIALS,
        VALIDATE_CERTS=settings.VALIDATE_CERTS,
    )


def reset_mail_runtime_caches() -> None:
    """Clear mail runtime caches for tests/tooling."""
    get_mail_config.cache_clear()


async def send_password_reset_email(email: str, token: str):
    start_time = time.time()
    settings = get_email_settings()
    reset_link = f"{settings.FRONTEND_BASE_URL}/reset-password#token={token}"

    try:
        message = MessageSchema(
            subject="Password Reset",
            recipients=[email],
            body=f"To reset your password, please click the following link:"
            f"\n\n{reset_link}\n\nIf you didn't request this, "
            f"you can ignore this email.",
            subtype=MessageType.plain,
        )
        fm = FastMail(get_mail_config())
        await fm.send_message(message)

        logger.info(
            "event=mail.password_reset_sent recipient=%s",
            redact_email(email),
        )
        log_security_event(
            "password_reset_email_sent", email, {"type": "password_reset"}
        )
        log_performance("send_password_reset_email", start_time)

    except Exception as e:
        logger.error(
            "event=mail.password_reset_send_failed recipient=%s error=%s",
            redact_email(email),
            str(e),
            exc_info=True,
        )
        log_security_event("password_reset_email_failed", email, {"error": str(e)})
        raise


async def send_alarm_email(alarm: Alarm):
    """Tell the configured alert recipients about an alarm, by catalogue name."""
    start_time = time.time()
    settings = get_email_settings()
    source = alarm.device_label or "an unknown device"
    readings = ", ".join(alarm.reading_labels.values()) or "not recorded"

    try:
        body = f"""
    Alarm on {source}

    Readings: {readings}
    Time: {alarm.timestamp.isoformat()}
    Type: {alarm.alarm_type}
    Value: {alarm.value}
    Alarm ID: {alarm.alarm_id}
    """
        recipients = settings.anomaly_alert_recipients_list
        message = MessageSchema(
            subject=f"Alarm on {source}",
            recipients=recipients,
            body=body,
            subtype=MessageType.plain,
        )
        fm = FastMail(get_mail_config())
        await fm.send_message(message)

        logger.warning(
            "event=mail.alarm_sent alarm_id=%s alarm_type=%s recipient_count=%s",
            alarm.alarm_id,
            alarm.alarm_type,
            len(recipients),
        )
        log_performance("send_alarm_email", start_time)

    except Exception as e:
        logger.error(
            "event=mail.alarm_send_failed alarm_id=%s alarm_type=%s error=%s",
            alarm.alarm_id,
            alarm.alarm_type,
            str(e),
            exc_info=True,
        )
        raise


async def send_invitation_email(email: str, token: str):
    settings = get_email_settings()
    link = f"{settings.FRONTEND_BASE_URL.rstrip('/')}/register#token={token}"
    message = MessageSchema(
        subject="Your aberration invitation",
        recipients=[email],
        body="You have been invited to this organization's aberration installation.\n\n"
        f"Choose your password: {link}\n\nThis link expires in 48 hours.",
        subtype=MessageType.plain,
    )
    await FastMail(get_mail_config()).send_message(message)
