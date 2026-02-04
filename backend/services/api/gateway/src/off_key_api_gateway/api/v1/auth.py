from fastapi import APIRouter, HTTPException, status
from jose import jwt, JWTError

from off_key_core.config.config import settings
from off_key_core.config.logs import logger, log_security_event
from off_key_core.schemas.user import (
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
from off_key_core.utils.enum import RoleEnum
from off_key_core.utils.mail import send_verification_email, send_password_reset_email
from ...facades.tactic import tactic

router = APIRouter()


@router.post("/register")
async def register(user: UserCreate):
    """Register user via TACTIC data service."""

    try:
        # Check if user already exists
        existing_user = await tactic.get_user_by_email(user.email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
            )

        # Create user data
        verification_token = create_verification_token(user.email)
        user_role = (
            user.role if user.email != settings.SUPERUSER_MAIL else RoleEnum.admin.value
        )

        user_data = {
            "email": user.email,
            "hashed_password": get_password_hash(user.password),
            "verification_token": verification_token,
            "role": user_role,
        }

        # Create user via TACTIC
        await tactic.create_user(user_data)

        # Log user registration
        logger.info(f"User registered successfully: {user.email}")
        log_security_event("user_registration", user.email, {"role": user_role})

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

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to register user: {str(e)}"
        )


@router.post("/login")
async def login(user: UserLogin):
    """Login user via TACTIC data service."""
    try:
        # Get user from TACTIC
        db_user = await tactic.get_user_by_email(user.email)

        if not db_user or not verify_password(user.password, db_user["hashed_password"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
            )

        if not db_user["is_verified"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Email not verified"
            )

        access_token = create_jwt({"sub": db_user["email"]})

        # Log successful login
        logger.info(f"User logged in successfully: {db_user['email']}")
        log_security_event("user_login_success", db_user["email"], {"role": db_user["role"]})

        return {"access_token": access_token, "token_type": "bearer"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to login: {str(e)}"
        )


@router.get("/verify-email")
async def verify_email(token: str):
    """Verify user email via TACTIC data service."""

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

        # Get user from TACTIC
        user = await tactic.get_user_by_email(email)
        if not user:
            logger.error(f"User not found for email: {email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User not found",
            )

        if user["is_verified"]:
            logger.info(f"User {email} is already verified")
            # Return success for already verified users (idempotent)
            return {"message": "Email verified successfully"}

        # Verify email via TACTIC
        result = await tactic.verify_user_email(email)

        # Log successful email verification
        logger.info(f"Email verified successfully: {email}")
        log_security_event(
            "email_verification_success", email, {"verification_method": "email_token"}
        )

        return result

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token"
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to verify email: {str(e)}"
        )


@router.post("/forgot-password")
async def forgot_password(user: ForgotPasswordRequest):
    """Initiate password reset via TACTIC data service."""
    email = user.email
    response_message = (
        "If the email is registered, a password reset link has been sent."
    )

    try:
        # Check if user exists via TACTIC
        db_user = await tactic.get_user_by_email(email)

        if db_user:
            reset_token = create_reset_token(email)
            logger.info(f"Sending password reset email to {email}")

            try:
                await send_password_reset_email(email, reset_token)
            except Exception as e:
                logger.error(f"Error sending password reset email: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Error sending the password reset email.",
                )

        # Always return the same response
        # Regardless of whether user exists (no user enumeration leak)
        return {"message": response_message}

    except HTTPException:
        raise
    except Exception:
        # Don't reveal if user lookup failed - still return success message
        return {"message": response_message}


@router.post("/reset-password")
async def reset_password(req: ResetPasswordRequest):
    """Reset user password via TACTIC data service."""

    try:
        payload = jwt.decode(
            req.token, settings.JWT_VERIFICATION_SECRET, algorithms=[settings.ALGORITHM]
        )
        if payload.get("token_type") != "password_reset":
            raise HTTPException(status_code=400, detail="Invalid token type")
        email = payload.get("sub")
        if email is None:
            raise HTTPException(status_code=400, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    try:
        # Check if user exists via TACTIC
        user = await tactic.get_user_by_email(email)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Update password via TACTIC
        new_password_hash = get_password_hash(req.new_password)
        await tactic.update_user_password(email, new_password_hash)

        logger.info(f"Password successfully reset for {email}")
        log_security_event("password_reset_success", email, {"reset_method": "email_token"})

        return {"message": "Password has been successfully reset"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reset password: {str(e)}"
        )
