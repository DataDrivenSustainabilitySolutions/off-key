from fastapi import Depends, Header, HTTPException, Request
from off_key_core.schemas.members import MemberProfile
from off_key_core.utils.enum import RoleEnum

from ..facades.tactic import TacticError, tactic
from .errors import raise_tactic_http_error


async def current_member(
    authorization: str | None = Header(default=None),
) -> MemberProfile:
    if not authorization:
        raise HTTPException(401, "Sign in to continue")
    try:
        result = await tactic._make_request(
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
