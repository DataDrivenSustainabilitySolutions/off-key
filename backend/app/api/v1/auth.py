import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwt, JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.logs import logger
from ...db.base import get_db_async
from ...db.models import User
from ...schemas.user import UserCreate, UserLogin
from ...services.auth import create_verification_token, get_password_hash, verify_password, create_jwt

router = APIRouter()


@router.post("/register")
async def register(user: UserCreate, db: AsyncSession = Depends(get_db_async)):
    result = await db.execute(select(User).filter(User.email == user.email))
    db_user = result.scalars().first()
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )

    # Create user
    verification_token = create_verification_token(user.email)
    db_user = User(
        email=user.email,
        hashed_password=get_password_hash(user.password),
        verification_token=verification_token,
        role=user.role
    )
    db.add(db_user)
    await db.flush()
    await db.commit()

    # Email details
    sender_email = 'sender@example.com'
    recipient_email = 'recipient@example.com'
    subject = 'Test Email'
    verification_link = f"{settings.BASE_URL}/v1/auth/verify-email?token={verification_token}"
    body = f"Click to verify: {verification_link}"

    logger.info(f"Sending verification link {verification_link}")

    # Create the email message
    message = MIMEMultipart()
    message['From'] = sender_email
    message['To'] = recipient_email
    message['Subject'] = subject
    message.attach(MIMEText(body, 'plain'))

    logger.info(f"Sending verification email to {user.email}")

    try:
        with smtplib.SMTP(settings.SMTP_SERVER, settings.SMTP_PORT) as server:
            server.starttls()
            server.send_message(message)
        print('Email sent successfully.')
    except Exception as e:
        print(f'Error sending email: {e}')
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send verification email: {e}"
        )

    return {"message": "Registration successful! Please check your email to verify your account."}


@router.post("/login")
async def login(user: UserLogin, db: AsyncSession = Depends(get_db_async)):
    result = await db.execute(select(User).filter(User.email == user.email))
    db_user = result.scalars().first()

    if not db_user or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    if not db_user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email not verified"
        )

    access_token = create_jwt({"sub": db_user.email})
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/verify-email")
async def verify_email(token: str, db: AsyncSession = Depends(get_db_async)):
    try:
        payload = jwt.decode(token, settings.JWT_VERIFICATION_SECRET, algorithms=["HS256"])
        if payload.get("token_type") != "email_verification":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid token type"
            )

        email = payload.get("sub")
        if email is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid token"
            )

        result = await db.execute(select(User).filter(User.email == email))
        user = result.scalars().first()

        if not user or user.is_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or already verified token"
            )

        user.is_verified = True
        user.verification_token = None
        await db.commit()

        return {"message": "Email verified successfully"}

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token"
        )
