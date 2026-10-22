import hashlib

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse
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

from ...facades.tactic import TacticError, tactic
from ...services.auth import create_jwt
from ..errors import TacticErrorRoute
from ..rate_limiter import client_ip, limiter

router = APIRouter(route_class=TacticErrorRoute)
REMEMBERED_SESSION_COOKIE = "off_key_remembered_session"
# One budget per client address across every credential endpoint, so a single
# source cannot spray guesses over many accounts or tokens.
auth_client_limit = limiter.shared_limit("30/minute", scope="auth-client")


def access_token_response(authenticated_user: dict) -> dict:
    user_id = authenticated_user.get("id")
    if type(user_id) is not int or user_id <= 0:
        raise HTTPException(502, "Authentication service returned an invalid user id")
    version = authenticated_user.get("session_version")
    if type(version) is not int or version < 0:
        raise HTTPException(502, "Authentication service returned an invalid session")
    return {
        "access_token": create_jwt(
            {
                "sub": authenticated_user["email"],
                "user_id": user_id,
                "session_version": version,
            }
        ),
        "token_type": "bearer",
        "user_id": user_id,
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


async def revoke_remembered_cookie(request: Request) -> None:
    token = remembered_token(request)
    if token:
        await tactic.request(
            "POST", "/api/v1/members/sessions/revoke", json_data={"token": token}
        )


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


@router.post("/register")
async def register():
    raise HTTPException(
        403, "Accounts are invitation-only. Ask an administrator for access."
    )


@router.post("/accept-invitation")
@limiter.limit("10/minute", key_func=auth_limit_key)
@auth_client_limit
async def accept_invitation(
    request: Request, invitation: AcceptInvitation = Depends(invitation_attempt)
):
    return await tactic.request(
        "POST",
        "/api/v1/members/accept-invitation",
        json_data=invitation.model_dump(),
    )


@router.post("/login")
@limiter.limit("10/minute", key_func=auth_limit_key)
@auth_client_limit
async def login(
    request: Request, response: Response, user: UserLogin = Depends(login_attempt)
):
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
        raise

    result = access_token_response(authenticated_user)
    await revoke_remembered_cookie(request)
    if user.remember_me:
        session = await tactic.request(
            "POST",
            "/api/v1/members/sessions",
            headers={"Authorization": f"Bearer {result['access_token']}"},
        )
        set_session_cookie(
            request, response, session["token"], REMEMBERED_SESSION_SECONDS
        )
    else:
        clear_session_cookie(request, response)

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
async def refresh_session(request: Request, response: Response):
    token = remembered_token(request)
    if token:
        try:
            user = await tactic.request(
                "POST", "/api/v1/members/sessions/refresh", json_data={"token": token}
            )
            response.headers["Cache-Control"] = "no-store"
            if user.get("token"):
                # Rotation keeps the original deadline; the old secret is spent.
                set_session_cookie(request, response, user["token"], user["expires_in"])
            return access_token_response(user)
        except TacticError as exc:
            if exc.status != 401:
                raise
    denied = JSONResponse({"detail": "Sign in to continue"}, status_code=401)
    clear_session_cookie(request, denied)
    return denied


@router.post("/logout", dependencies=[Depends(session_request)])
async def logout(request: Request, response: Response):
    try:
        await revoke_remembered_cookie(request)
    except TacticError:
        # Still remove the browser credential during a temporary service outage.
        response = JSONResponse(
            {"detail": "Session service unavailable"}, status_code=503
        )
        clear_session_cookie(request, response)
        return response
    clear_session_cookie(request, response)
    return {"message": "Signed out"}


@router.get("/verify-email")
async def verify_email():
    raise HTTPException(
        410, "This verification link is no longer supported. Request an invitation."
    )


async def deliver_password_reset(email: str, token: str) -> None:
    try:
        await send_password_reset_email(email, token)
    except Exception:
        # Preserve the same response for unknown accounts and mail failures.
        logger.error("event=password_reset_delivery_failed")


@router.post("/forgot-password")
@limiter.limit("5/minute", key_func=auth_limit_key)
@auth_client_limit
async def forgot_password(
    request: Request,
    background: BackgroundTasks,
    user: ForgotPasswordRequest = Depends(reset_email_attempt),
):
    result = await tactic.request(
        "POST",
        "/api/v1/members/request-password-reset",
        json_data=user.model_dump(),
    )
    if result:
        # Deliver after responding so mail latency does not reveal the account.
        background.add_task(deliver_password_reset, result["email"], result["token"])
    return {
        "message": "If the email is registered, a password reset link has been sent."
    }


@router.post("/reset-password")
@limiter.limit("10/minute", key_func=auth_limit_key)
@auth_client_limit
async def reset_password(
    request: Request, reset: PasswordReset = Depends(reset_attempt)
):
    return await tactic.request(
        "POST",
        "/api/v1/members/reset-password",
        json_data=reset.model_dump(),
    )
