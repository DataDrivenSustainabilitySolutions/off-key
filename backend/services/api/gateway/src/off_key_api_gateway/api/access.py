import hashlib
import time
from collections import OrderedDict

from fastapi import Depends, Header, HTTPException, Request
from off_key_core.schemas.members import MemberProfile
from off_key_core.utils.enum import RoleEnum

from ..facades.tactic import TacticError, tactic
from .errors import raise_tactic_http_error

# Polling views send several requests per second with one token. A short-lived
# cache spares TACTIC a membership lookup for each, while role, password and
# deactivation changes still take effect within MEMBER_CACHE_SECONDS.
MEMBER_CACHE_SECONDS = 5.0
MEMBER_CACHE_SIZE = 1024
_members: OrderedDict[str, tuple[float, MemberProfile]] = OrderedDict()


def clear_member_cache() -> None:
    _members.clear()


async def current_member(
    authorization: str | None = Header(default=None),
) -> MemberProfile:
    if not authorization:
        raise HTTPException(401, "Sign in to continue")
    key = hashlib.sha256(authorization.encode()).hexdigest()
    cached = _members.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    try:
        result = await tactic._make_request(
            "GET",
            "/api/v1/members/me",
            headers={"Authorization": authorization},
        )
    except TacticError as exc:
        _members.pop(key, None)
        raise_tactic_http_error(exc)
    member = MemberProfile.model_validate(result)
    _members[key] = (time.monotonic() + MEMBER_CACHE_SECONDS, member)
    _members.move_to_end(key)
    while len(_members) > MEMBER_CACHE_SIZE:
        _members.popitem(last=False)
    return member


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
