from fastapi import APIRouter, HTTPException, status
from off_key_core.config.auth import get_auth_settings
from off_key_core.config.logs import log_security_event, logger, redact_email
from off_key_core.schemas.user import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    UserCreate,
    UserLogin,
)
from off_key_core.utils.enum import RoleEnum
from off_key_core.utils.mail import send_password_reset_email, send_verification_email

from ...facades.tactic import TacticError, tactic
from ...services.auth import (
    create_jwt,
    create_reset_token,
    create_verification_token,
    get_password_hash,
    verify_reset_token,
    verify_verification_token,
)
from ..errors import raise_tactic_http_error

router = APIRouter()


def _parse_user_id(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.isdigit():
        parsed = int(value)
        return parsed if parsed > 0 else None
    return None


async def _resolve_authenticated_user_id(
    authenticated_user: dict[str, object],
) -> int:
    user_id = _parse_user_id(authenticated_user.get("id"))
    if user_id is not None:
        return user_id

    user_id = _parse_user_id(authenticated_user.get("user_id"))
    if user_id is not None:
        return user_id

    email = authenticated_user.get("email")
    if not isinstance(email, str) or not email:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Authentication service response did not include a user email",
        )

    try:
        user_record = await tactic.get_user_by_email(email)
    except TacticError as e:
        raise_tactic_http_error(e)

    if not user_record:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Authentication service could not resolve the user profile",
        )

    user_id = _parse_user_id(user_record.get("id"))
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Authentication service response did not include a user id",
        )

    return user_id


@router.post("/register")
async def register(user: UserCreate):
    settings = get_auth_settings()
    try:
        existing_user = await tactic.get_user_by_email(user.email)
    except TacticError as e:
        raise_tactic_http_error(e)

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )

    # Create user
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
    try:
        await tactic.create_user(user_data)
    except TacticError as e:
        if e.status in (status.HTTP_400_BAD_REQUEST, status.HTTP_409_CONFLICT):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            ) from e
        raise_tactic_http_error(e)

    safe_email = redact_email(user.email)
    logger.info("event=auth.user_registered email=%s role=%s", safe_email, user_role)
    log_security_event("user_registration", user.email, {"role": user_role})

    logger.info("event=auth.verification_email_requested email=%s", safe_email)

    try:
        await send_verification_email(user.email, verification_token)
        logger.info("event=auth.verification_email_sent email=%s", safe_email)
    except Exception as e:
        logger.error(
            "event=auth.verification_email_send_failed email=%s error=%s",
            safe_email,
            str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send verification email: {e}",
        ) from e

    return {
        "message": "Registration successful! Check your email to verify your account."
    }


@router.post("/login")
async def login(user: UserLogin):
    try:
        authenticated_user = await tactic.authenticate_user(
            email=user.email,
            password=user.password,
        )
    except TacticError as e:
        if e.status in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN):
            log_security_event(
                "user_login_failed",
                user.email,
                {"status": e.status},
            )
        raise_tactic_http_error(e)

    user_id = await _resolve_authenticated_user_id(authenticated_user)
    access_token = create_jwt(
        {
            "sub": authenticated_user["email"],
            "user_id": user_id,
        }
    )

    safe_email = redact_email(authenticated_user["email"])
    logger.info("event=auth.user_logged_in email=%s", safe_email)
    log_security_event(
        "user_login_success",
        authenticated_user["email"],
        {"role": authenticated_user["role"]},
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user_id,
    }


@router.get("/verify-email")
async def verify_email(token: str):
    email = verify_verification_token(token)
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token"
        )

    safe_email = redact_email(email)
    logger.info("event=auth.verification_requested email=%s", safe_email)
    try:
        user = await tactic.get_user_by_email(email)
    except TacticError as e:
        raise_tactic_http_error(e)

    if not user:
        logger.warning("event=auth.verification_user_missing email=%s", safe_email)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User not found",
        )

    if user.get("is_verified"):
        logger.info("event=auth.user_already_verified email=%s", safe_email)
        # Return success for already verified users (idempotent)
        return {"message": "Email verified successfully"}

    try:
        result = await tactic.verify_user_email(email)
    except TacticError as e:
        raise_tactic_http_error(e)

    logger.info("event=auth.verification_success email=%s", safe_email)
    log_security_event(
        "email_verification_success", email, {"verification_method": "email_token"}
    )

    return result


@router.post("/forgot-password")
async def forgot_password(user: ForgotPasswordRequest):
    email = user.email
    response_message = (
        "If the email is registered, a password reset link has been sent."
    )

    try:
        existing_user = await tactic.get_user_by_email(email)
    except TacticError as e:
        raise_tactic_http_error(e)

    if existing_user:
        reset_token = create_reset_token(existing_user["email"])
        logger.info(
            "event=auth.password_reset_email_requested email=%s",
            redact_email(email),
        )

        try:
            await send_password_reset_email(email, reset_token)
        except Exception as e:
            logger.error(
                "event=auth.password_reset_email_send_failed email=%s error=%s",
                redact_email(email),
                str(e),
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error sending the password reset email.",
            ) from e

    # Always return the same response
    # Regardless of whether user exists (no user enumeration leak)
    return {"message": response_message}


@router.post("/reset-password")
async def reset_password(req: ResetPasswordRequest):
    email = verify_reset_token(req.token)
    if email is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    try:
        user = await tactic.get_user_by_email(email)
    except TacticError as e:
        raise_tactic_http_error(e)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Update password
    new_password_hash = get_password_hash(req.new_password)
    try:
        await tactic.update_user_password(email, new_password_hash)
    except TacticError as e:
        raise_tactic_http_error(e)

    logger.info("event=auth.password_reset_success email=%s", redact_email(email))
    log_security_event("password_reset_success", email, {"reset_method": "email_token"})

    return {"message": "Password has been successfully reset"}
