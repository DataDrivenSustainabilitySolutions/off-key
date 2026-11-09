from functools import cache

from aberration_core.auth.permissions import Permission
from aberration_core.schemas.members import MemberProfile
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

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


def _refuse_without(permission: Permission, user: MemberProfile) -> None:
    if permission not in user.permissions:
        raise HTTPException(403, f"This needs the {permission} permission")


@cache
def require_permission(permission: Permission):
    """One dependency per permission, so access tests can tell them apart."""

    async def holds_permission(
        user: MemberProfile = Depends(current_member),
    ) -> MemberProfile:
        _refuse_without(permission, user)
        return user

    holds_permission.__name__ = f"require_{permission}"
    return holds_permission


@cache
def writes_require(permission: Permission):
    """Every member reads; changing anything needs ``permission``."""

    async def reads_open_writes_checked(
        request: Request, user: MemberProfile = Depends(current_member)
    ) -> None:
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            _refuse_without(permission, user)

    reads_open_writes_checked.__name__ = f"writes_require_{permission}"
    return reads_open_writes_checked
