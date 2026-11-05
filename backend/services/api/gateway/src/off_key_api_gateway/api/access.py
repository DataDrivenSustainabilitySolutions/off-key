from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from off_key_core.schemas.members import MemberProfile
from off_key_core.utils.enum import RoleEnum

from ..facades.tactic import TacticError, tactic
from .errors import raise_tactic_http_error

# Declared once so the OpenAPI document names the scheme and every protected
# operation lists it, instead of an "authorization" parameter that generated
# clients and agent tools would ask the caller to fill in.
bearer = HTTPBearer(
    scheme_name="bearerAuth",
    bearerFormat="JWT",
    description=(
        "Access token from `POST /v1/auth/login`, sent as "
        "`Authorization: Bearer <token>`."
    ),
    auto_error=False,
)


async def member_authorization(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    """The caller's bearer credential, forwarded unchanged to TACTIC."""
    if credentials is None:
        raise HTTPException(401, "Sign in to continue")
    return f"Bearer {credentials.credentials}"


async def current_member(
    authorization: str = Depends(member_authorization),
) -> MemberProfile:
    try:
        result = await tactic.request(
            "GET",
            "/api/v1/members/me",
            headers={"Authorization": authorization},
        )
    except TacticError as exc:
        raise_tactic_http_error(exc)
    return MemberProfile.model_validate(result)


async def require_admin(user: MemberProfile = Depends(current_member)) -> MemberProfile:
    if user.role != RoleEnum.admin:
        raise HTTPException(403, "Administrator access required")
    return user


async def operational_access(
    request: Request,
    user: MemberProfile = Depends(current_member),
) -> None:
    if request.method not in {"GET", "HEAD", "OPTIONS"} and user.role != RoleEnum.admin:
        raise HTTPException(403, "Administrator access required")
