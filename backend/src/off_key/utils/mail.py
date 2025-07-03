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
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True,
)


async def send_verification_email(email: str, token: str):
    verification_link = f"http://localhost:3000/verify?token={token}"
    message = MessageSchema(
        subject="Email Verification",
        recipients=[email],
        body=f"Please verify your email by clicking this link: {verification_link}",
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
        recipients=["admin@example.com"],  # anpassen nach Bedarf
        body=body,
        subtype="plain",
    )
    fm = FastMail(conf)
    await fm.send_message(message)