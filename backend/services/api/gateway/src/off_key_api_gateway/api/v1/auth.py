import hashlib
from collections.abc import Mapping
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
)
from fastapi.responses import JSONResponse
from off_key_core.auth.tokens import AccessClaims, issue_access_token
from off_key_core.config.logs import log_security_event, logger, redact_email
from off_key_core.schemas.members import AcceptInvitation, PasswordReset
from off_key_core.schemas.sessions import (
    REMEMBERED_SESSION_SECONDS,
    RememberedSessionToken,
)
from off_key_core.schemas.user import (
    ForgotPasswordRequest,
    UserLogin,
)
from off_key_core.utils.mail import send_password_reset_email
from off_key_tactic_middleware.domain import AuthenticationError
from off_key_tactic_middleware.services.accounts.members import MemberService
from off_key_tactic_middleware.services.accounts.remembered_sessions import (
    RememberedSessionService,
)
from off_key_tactic_middleware.services.accounts.users import UserService
from sqlalchemy.exc import SQLAlchemyError

from ...providers import (
    get_member_service,
    get_remembered_session_service,
    get_user_service,
)
from ..errors import DomainErrorRoute
from ..rate_limiter import client_ip, limiter

router = APIRouter(route_class=DomainErrorRoute)
REMEMBERED_SESSION_COOKIE = "off_key_remembered_session"
# One budget per client address across every credential endpoint, so a single
# source cannot spray guesses over many accounts or tokens.
auth_client_limit = limiter.shared_limit("30/minute", scope="auth-client")


def access_token_response(identity: Mapping[str, Any]) -> dict:
    """A bearer token for a member whose credentials were just checked."""
    return {
        "access_token": issue_access_token(
            AccessClaims(
                sub=identity["email"],
                user_id=identity["id"],
                session_version=identity["session_version"],
                session_family=identity.get("session_family"),
            )
        ),
        "token_type": "bearer",
        "member_id": identity["id"],
    }


def secure_session_cookie(request: Request) -> bool:
    # Plain HTTP is supported only for loopback development. Public deployments
    # keep Secure even when HTTPS terminates before the gateway.
    return not (
        request.url.scheme == "http"
        and request.url.hostname in {"localhost", "127.0.0.1", "::1"}
    )


def set_session_cookie(
    request: Request, response: Response, token: str, max_age: int
) -> None:
    response.set_cookie(
        REMEMBERED_SESSION_COOKIE,
        token,
        max_age=max_age,
        path="/",
        secure=secure_session_cookie(request),
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"


def clear_session_cookie(request: Request, response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.delete_cookie(
        REMEMBERED_SESSION_COOKIE,
        path="/",
        secure=secure_session_cookie(request),
        httponly=True,
        samesite="lax",
    )


def session_request(request: Request) -> None:
    # A custom header requires a successful CORS preflight for cross-origin
    # callers, including other sites under the same parent domain.
    if request.headers.get("X-Off-Key-Session") != "1":
        raise HTTPException(403, "Session request header required")


def remembered_token(request: Request) -> str | None:
    value = request.cookies.get(REMEMBERED_SESSION_COOKIE)
    if value is None:
        return None
    try:
        return RememberedSessionToken(token=value).token
    except ValueError:
        return None


async def revoke_remembered_cookie(
    request: Request, sessions: RememberedSessionService
) -> None:
    token = remembered_token(request)
    if token:
        await sessions.revoke(token)


def login_attempt(request: Request, user: UserLogin) -> UserLogin:
    # Pairing the account with the client keeps others from locking it out.
    request.state.auth_identity = f"{client_ip(request)}|{user.email}"
    return user


def reset_email_attempt(
    request: Request, user: ForgotPasswordRequest
) -> ForgotPasswordRequest:
    request.state.auth_identity = f"{client_ip(request)}|{user.email}"
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


@router.post("/accept-invitation")
@limiter.limit("10/minute", key_func=auth_limit_key)
@auth_client_limit
async def accept_invitation(
    request: Request,
    invitation: AcceptInvitation = Depends(invitation_attempt),
    members: MemberService = Depends(get_member_service),
):
    """Choose a password with the token from an invitation email."""
    await members.accept_invitation(invitation.token, invitation.password)
    return {"message": "Account activated. You can now sign in."}


@router.post("/login")
@limiter.limit("10/minute", key_func=auth_limit_key)
@auth_client_limit
async def login(
    request: Request,
    response: Response,
    user: UserLogin = Depends(login_attempt),
    users: UserService = Depends(get_user_service),
    sessions: RememberedSessionService = Depends(get_remembered_session_service),
):
    """Exchange email and password for a bearer access token.

    Send the token as `Authorization: Bearer <token>`. It expires after the
    installation's token lifetime, 30 minutes unless configured otherwise;
    sign in again then. `remember_me` is for browsers: it also sets a
    session cookie that `/v1/auth/refresh` trades for new tokens.
    """
    try:
        authenticated_user = await users.authenticate(
            email=user.email,
            password=user.password,
        )
    except AuthenticationError:
        log_security_event("user_login_failed", user.email, {"status": 401})
        raise

    await revoke_remembered_cookie(request, sessions)
    if user.remember_me:
        session = await sessions.create(
            user_id=authenticated_user["id"],
            session_version=authenticated_user["session_version"],
        )
        set_session_cookie(
            request, response, session["token"], REMEMBERED_SESSION_SECONDS
        )
        result = access_token_response(
            authenticated_user | {"session_family": session["session_family"]}
        )
    else:
        clear_session_cookie(request, response)
        result = access_token_response(authenticated_user)

    safe_email = redact_email(authenticated_user["email"])
    logger.info("event=auth.user_logged_in email=%s", safe_email)
    log_security_event(
        "user_login_success",
        authenticated_user["email"],
        {"role": authenticated_user["role"]},
    )

    return result


@router.post("/refresh", dependencies=[Depends(session_request)])
@limiter.limit("60/minute")
async def refresh_session(
    request: Request,
    response: Response,
    sessions: RememberedSessionService = Depends(get_remembered_session_service),
):
    """Browser only: trade the remembered-session cookie for a new access token.

    Needs the header `X-Off-Key-Session: 1`.
    """
    token = remembered_token(request)
    if token:
        try:
            user = await sessions.refresh(token)
        except AuthenticationError:
            pass
        else:
            response.headers["Cache-Control"] = "no-store"
            if user.get("token"):
                # Rotation keeps the original deadline; the old secret is spent.
                set_session_cookie(request, response, user["token"], user["expires_in"])
            return access_token_response(user)
    denied = JSONResponse({"detail": "Sign in to continue"}, status_code=401)
    clear_session_cookie(request, denied)
    return denied


@router.post("/logout", dependencies=[Depends(session_request)])
@limiter.limit("60/minute")
async def logout(
    request: Request,
    response: Response,
    sessions: RememberedSessionService = Depends(get_remembered_session_service),
):
    """Revoke the supplied bearer token and the browser's remembered session.

    Needs the header `X-Off-Key-Session: 1`.
    """
    try:
        await revoke_remembered_cookie(request, sessions)
        scheme, _, credential = request.headers.get("Authorization", "").partition(" ")
        if scheme.lower() == "bearer" and credential:
            await sessions.revoke_access(credential)
    except SQLAlchemyError:
        # Still remove the browser credential during a temporary database outage.
        response = JSONResponse(
            {"detail": "Session service unavailable"}, status_code=503
        )
        clear_session_cookie(request, response)
        return response
    clear_session_cookie(request, response)
    return {"message": "Signed out"}


async def deliver_password_reset(email: str, token: str) -> None:
    try:
        await send_password_reset_email(email, token)
    except Exception:
        # Preserve the same response for unknown accounts and mail failures.
        logger.error("event=password_reset_delivery_failed")


@router.post("/password-reset")
@limiter.limit("5/minute", key_func=auth_limit_key)
@auth_client_limit
async def request_password_reset(
    request: Request,
    background: BackgroundTasks,
    user: ForgotPasswordRequest = Depends(reset_email_attempt),
    members: MemberService = Depends(get_member_service),
):
    """Email a password-reset link if the address belongs to a member.

    The answer is the same either way, so it reveals no accounts.
    """
    result = await members.issue_reset_token(str(user.email))
    if result:
        # Deliver after responding so mail latency does not reveal the account.
        background.add_task(deliver_password_reset, result["email"], result["token"])
    return {
        "message": "If the email is registered, a password reset link has been sent."
    }


@router.post("/password-reset/confirm")
@limiter.limit("10/minute", key_func=auth_limit_key)
@auth_client_limit
async def confirm_password_reset(
    request: Request,
    reset: PasswordReset = Depends(reset_attempt),
    members: MemberService = Depends(get_member_service),
):
    """Set a new password with the token from a reset email."""
    await members.reset_password(reset.token, reset.new_password)
    return {"message": "Password has been successfully reset"}
