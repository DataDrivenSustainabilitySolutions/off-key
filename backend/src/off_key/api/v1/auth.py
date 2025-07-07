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
from ...utils.mail import send_verification_email, send_password_reset_email

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

    # Send verification email
    logger.info(f"Sending verification email to {user.email}")
    
    try:
        await send_verification_email(user.email, verification_token)
        logger.info("Verification email sent successfully.")
    except Exception as e:
        logger.error(f"Error sending verification email: {e}")
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
            token, settings.JWT_VERIFICATION_SECRET, algorithms=[settings.ALGORITHM]
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

        logger.info(f"Verifying email: {email}")
        result = await db.execute(select(User).filter(User.email == email))
        user = result.scalars().first()

        if not user:
            logger.error(f"User not found for email: {email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User not found",
            )

        if user.is_verified:
            logger.info(f"User {email} is already verified")
            # Return success for already verified users (idempotent)
            return {"message": "Email verified successfully"}

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
        "If the email is registered, a password reset link has been sent."
    )

    result = await db.execute(select(User).filter(User.email == email))
    user = result.scalars().first()

    if user:
        reset_token = create_reset_token(user.email)
        logger.info(f"Sending password reset email to {email}")

        try:
            await send_password_reset_email(email, reset_token)
        except Exception as e:
            logger.error(f"Error sending password reset email: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error sending the password reset email.",
            )

    # Always return the same response, regardless of whether user exists (no user enumeration leak)
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
            raise HTTPException(status_code=400, detail="Invalid token type")
        email = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=400, detail="Invalid token")
    except JWTError:
        raise HTTPException(
            status_code=400, detail="Invalid or expired token"
        )

    # Find user
    result = await db.execute(select(User).filter(User.email == email))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update password
    user.hashed_password = get_password_hash(req.new_password)
    await db.commit()

    logger.info(f"Password successfully reset for {email}")

    return {"message": "Password has been successfully reset"}
