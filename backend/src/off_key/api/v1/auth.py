import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwt, JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from off_key.core.config import settings

from ...core.logs import logger
from ...db.base import get_db_async
from ...db.models import User
from ...schemas.user import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    UserCreate,
    UserLogin,
)
from ...services.auth import (
    create_reset_token,
    create_verification_token,
    get_password_hash,
    verify_password,
    create_jwt,
)
from ...utils.enum import RoleEnum

router = APIRouter()


@router.post("/register")
async def register(user: UserCreate, db: AsyncSession = Depends(get_db_async)):
    result = await db.execute(select(User).filter(User.email == user.email))
    db_user = result.scalars().first()
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    # Create user
    verification_token = create_verification_token(user.email)

    user_role = (
        user.role if user.email != settings.SUPERUSER_MAIL else RoleEnum.admin.value
    )

    db_user = User(
        email=user.email,
        hashed_password=get_password_hash(user.password),
        verification_token=verification_token,
        role=user_role,
    )

    db.add(db_user)
    await db.flush()
    await db.commit()

    # Email details
    sender_email = "sender@example.com"
    recipient_email = user.email
    subject = "Test Email"
    verification_link = (
        f"{settings.BASE_URL}/v1/auth/verify-email?token={verification_token}"
    )
    body = f"Click to verify: {verification_link}"

    logger.info(f"Sending verification link {verification_link}")

    # Create the email message
    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = recipient_email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    logger.info(f"Sending verification email to {user.email}")

    try:
        with smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT) as server:
            # server.starttls() ohne tls für mailpit
            server.send_message(message)
        print("Email sent successfully.")
    except Exception as e:
        print(f"Error sending email: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send verification email: {e}",
        )

    return {
        "message": "Registration successful! Check your email to verify your account."
    }


@router.post("/login")
async def login(user: UserLogin, db: AsyncSession = Depends(get_db_async)):
    result = await db.execute(select(User).filter(User.email == user.email))
    db_user = result.scalars().first()

    if not db_user or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    if not db_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Email not verified"
        )

    access_token = create_jwt({"sub": db_user.email})
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/verify-email")
async def verify_email(token: str, db: AsyncSession = Depends(get_db_async)):
    try:
        payload = jwt.decode(
            token, settings.JWT_VERIFICATION_SECRET, algorithms=["HS256"]
        )
        if payload.get("token_type") != "email_verification":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token type"
            )

        email = payload.get("sub")
        if email is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token"
            )

        result = await db.execute(select(User).filter(User.email == email))
        user = result.scalars().first()

        if not user or user.is_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or already verified token",
            )

        user.is_verified = True
        user.verification_token = None
        await db.commit()

        return {"message": "Email verified successfully"}

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token"
        )


@router.post("/forgot-password")
async def forgot_password(
    user: ForgotPasswordRequest, db: AsyncSession = Depends(get_db_async)
):
    email = user.email
    response_message = (
        "Wenn die E-Mail registriert ist, wurde ein Link zum Zurücksetzen gesendet."
    )

    result = await db.execute(select(User).filter(User.email == email))
    user = result.scalars().first()

    if user:
        reset_token = create_reset_token(user.email)
        reset_link = f"{settings.FRONTEND_BASE_URL}/reset-password?token={reset_token}"
        # Email vorbereiten
        sender_email = "noreply@example.com"
        recipient_email = email
        subject = "Passwort zurücksetzen"
        body = (
            f"Hallo,\n\n"
            f"um dein Passwort zurückzusetzen, klicke bitte auf folgenden Link:\n\n"
            f"{reset_link}\n\n"
            f"Wenn du das nicht angefordert hast, kannst du diese Mail ignorieren."
        )

        message = MIMEMultipart()
        message["From"] = sender_email
        message["To"] = recipient_email
        message["Subject"] = subject
        message.attach(MIMEText(body, "plain"))

        logger.info(f"Sending password reset email to {email}")

        try:
            with smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT) as server:
                # kein TLS für Mailpit nötig
                server.send_message(message)
        except Exception as e:
            logger.error(f"Error sending password reset email: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error sending the password reset email.",
            )

    # Antwort immer gleich, egal ob User existiert (kein User Enumeration Leak)
    return {"message": response_message}


@router.post("/reset-password")
async def reset_password(
    req: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db_async),
):
    try:
        payload = jwt.decode(
            req.token, settings.JWT_VERIFICATION_SECRET, algorithms=["HS256"]
        )
        if payload.get("token_type") != "password_reset":
            raise HTTPException(status_code=400, detail="Ungültiger Token-Typ")
        email = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=400, detail="Ungültiger Token")
    except JWTError:
        raise HTTPException(
            status_code=400, detail="Ungültiger oder abgelaufener Token"
        )

    # User finden
    result = await db.execute(select(User).filter(User.email == email))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")

    # Passwort updaten
    user.hashed_password = get_password_hash(req.new_password)
    await db.commit()

    logger.info(f"Passwort erfolgreich zurückgesetzt für {email}")

    return {"message": "Passwort wurde erfolgreich zurückgesetzt"}
