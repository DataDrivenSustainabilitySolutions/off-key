from fastapi_mail import FastMail, MessageSchema, ConnectionConfig
from off_key.core.config import settings

conf = ConnectionConfig(
    MAIL_USERNAME=settings.EMAIL_USERNAME,
    MAIL_PASSWORD=settings.EMAIL_PASSWORD,
    MAIL_FROM=settings.EMAIL_FROM,
    MAIL_PORT=settings.SMTP_PORT,
    MAIL_SERVER=settings.SMTP_SERVER,
    MAIL_SSL_TLS=settings.MAIL_SSL_TLS,
    MAIL_STARTTLS=settings.MAIL_STARTTLS,
    USE_CREDENTIALS=settings.USE_CREDENTIALS,
    VALIDATE_CERTS=settings.VALIDATE_CERTS,
)


async def send_verification_email(email: str, token: str):
    verification_link = f"{settings.FRONTEND_BASE_URL}/verify?token={token}"
    message = MessageSchema(
        subject="Email Verification",
        recipients=[email],
        body=f"Please verify your email by clicking this link: {verification_link}",
        subtype="plain",
    )
    fm = FastMail(conf)
    await fm.send_message(message)


async def send_password_reset_email(email: str, token: str):
    reset_link = f"{settings.FRONTEND_BASE_URL}/reset-password?token={token}"
    message = MessageSchema(
        subject="Password Reset",
        recipients=[email],
        body=f"To reset your password, please click the following link:"
        f"\n\n{reset_link}\n\nIf you didn't request this, "
        f"you can ignore this email.",
        subtype="plain",
    )
    fm = FastMail(conf)
    await fm.send_message(message)


async def send_anomaly_alert_email(anomaly: dict):
    body = f"""
    Anomaly Detected

    Charger ID: {anomaly['charger_id']}
    Timestamp: {anomaly['timestamp']}
    Telemetry Type: {anomaly['telemetry_type']}
    Anomaly Type: {anomaly['anomaly_type']}
    Anomaly Value: {anomaly['anomaly_value']}
    """
    message = MessageSchema(
        subject=f"Anomaly Detected - Charger {anomaly['charger_id']}",
        recipients=settings.anomaly_alert_recipients_list,
        body=body,
        subtype="plain",
    )
    fm = FastMail(conf)
    await fm.send_message(message)
