import hashlib

from fastapi import APIRouter, Depends, HTTPException, Request, status
from off_key_core.config.logs import log_security_event, logger, redact_email
from off_key_core.schemas.members import AcceptInvitation, PasswordReset
from off_key_core.schemas.user import (
    ForgotPasswordRequest,
    UserLogin,
)
from off_key_core.utils.mail import send_password_reset_email

from ...facades.tactic import TacticError, tactic
from ...services.auth import create_jwt
from ..errors import raise_tactic_http_error
from ..rate_limiter import limiter

router = APIRouter()


def login_attempt(request: Request, user: UserLogin) -> UserLogin:
    request.state.auth_identity = str(user.email).casefold()
    return user


def reset_email_attempt(
    request: Request, user: ForgotPasswordRequest
) -> ForgotPasswordRequest:
    request.state.auth_identity = str(user.email).casefold()
    return user


def invitation_attempt(
    request: Request, invitation: AcceptInvitation
) -> AcceptInvitation:
    request.state.auth_identity = invitation.token
    return invitation


def reset_attempt(request: Request, reset: PasswordReset) -> PasswordReset:
    request.state.auth_identity = reset.token
    return reset


def auth_limit_key(request: Request) -> str:
    # Keep emails and single-use tokens out of limiter storage and error logs.
    return hashlib.sha256(request.state.auth_identity.encode()).hexdigest()


@router.post("/register")
async def register():
    raise HTTPException(
        403, "Accounts are invitation-only. Ask an administrator for access."
    )


@router.post("/accept-invitation")
@limiter.limit("10/minute", key_func=auth_limit_key)
async def accept_invitation(
    request: Request, invitation: AcceptInvitation = Depends(invitation_attempt)
):
    try:
        return await tactic._make_request(
            "POST",
            "/api/v1/members/accept-invitation",
            json_data=invitation.model_dump(),
        )
    except TacticError as exc:
        raise_tactic_http_error(exc)


@router.post("/login")
@limiter.limit("10/minute", key_func=auth_limit_key)
async def login(request: Request, user: UserLogin = Depends(login_attempt)):
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

    user_id = authenticated_user.get("id")
    if type(user_id) is not int or user_id <= 0:
        raise HTTPException(502, "Authentication service returned an invalid user id")
    version = authenticated_user.get("session_version")
    if type(version) is not int or version < 0:
        raise HTTPException(502, "Authentication service returned an invalid session")
    access_token = create_jwt(
        {
            "sub": authenticated_user["email"],
            "user_id": user_id,
            "session_version": version,
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
async def verify_email():
    raise HTTPException(
        410, "This verification link is no longer supported. Request an invitation."
    )


@router.post("/forgot-password")
@limiter.limit("5/minute", key_func=auth_limit_key)
async def forgot_password(
    request: Request, user: ForgotPasswordRequest = Depends(reset_email_attempt)
):
    try:
        result = await tactic._make_request(
            "POST",
            "/api/v1/members/request-password-reset",
            json_data=user.model_dump(),
        )
    except TacticError as exc:
        raise_tactic_http_error(exc)
    if result:
        try:
            await send_password_reset_email(result["email"], result["token"])
        except Exception:
            # Preserve the same response for unknown accounts and mail failures.
            logger.error("event=password_reset_delivery_failed")
    return {
        "message": "If the email is registered, a password reset link has been sent."
    }


@router.post("/reset-password")
@limiter.limit("10/minute", key_func=auth_limit_key)
async def reset_password(
    request: Request, reset: PasswordReset = Depends(reset_attempt)
):
    try:
        return await tactic._make_request(
            "POST",
            "/api/v1/members/reset-password",
            json_data=reset.model_dump(),
        )
    except TacticError as exc:
        raise_tactic_http_error(exc)
