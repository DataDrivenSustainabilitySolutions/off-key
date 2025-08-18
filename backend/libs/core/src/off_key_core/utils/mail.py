import time
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig
from ..config.config import settings
from ..config.logs import logger, log_performance, log_security_event

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
    start_time = time.time()
    verification_link = f"{settings.FRONTEND_BASE_URL}/verify?token={token}"

    try:
        message = MessageSchema(
            subject="Email Verification",
            recipients=[email],
            body=f"Please verify your email by clicking this link: {verification_link}",
            subtype="plain",
        )
        fm = FastMail(conf)
        await fm.send_message(message)

        logger.info(f"Verification email sent successfully to {email}")
        log_security_event("verification_email_sent", email, {"type": "registration"})
        log_performance("send_verification_email", start_time)

    except Exception as e:
        logger.error(f"Failed to send verification email to {email}: {str(e)}")
        log_security_event("verification_email_failed", email, {"error": str(e)})
        raise


async def send_password_reset_email(email: str, token: str):
    start_time = time.time()
    reset_link = f"{settings.FRONTEND_BASE_URL}/reset-password?token={token}"

    try:
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

        logger.info(f"Password reset email sent successfully to {email}")
        log_security_event(
            "password_reset_email_sent", email, {"type": "password_reset"}
        )
        log_performance("send_password_reset_email", start_time)

    except Exception as e:
        logger.error(f"Failed to send password reset email to {email}: {str(e)}")
        log_security_event("password_reset_email_failed", email, {"error": str(e)})
        raise


async def send_anomaly_alert_email(anomaly: dict):
    start_time = time.time()
    charger_id = anomaly.get("charger_id", "unknown")
    anomaly_type = anomaly.get("anomaly_type", "unknown")

    try:
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

        logger.warning(
            f"Anomaly alert email sent for charger {charger_id} | "
            f"Type: {anomaly_type} |"
            f" Recipients: {len(settings.anomaly_alert_recipients_list)}"
        )
        log_performance("send_anomaly_alert_email", start_time)

    except Exception as e:
        logger.error(
            f"Failed to send anomaly alert email for charger {charger_id}: {str(e)} | "
            f"Anomaly type: {anomaly_type}"
        )
        raise
