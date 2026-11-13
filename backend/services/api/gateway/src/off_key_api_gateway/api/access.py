from functools import cache

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from off_key_core.auth.agents import AGENT_KEY_PREFIX, agent_refusal, is_agent_key
from off_key_core.auth.permissions import Permission
from off_key_core.schemas.agents import AgentProfile
from off_key_core.schemas.members import MemberProfile

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
        "`Authorization: Bearer <token>`. An agent sends its key the same way. "
        f"A key starts with `{AGENT_KEY_PREFIX}` and reaches only the operations "
        "marked `x-agent-access`: `any` for every key, `start` for a key that "
        "may start monitoring services."
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


async def signed_in_member(authorization: str) -> MemberProfile:
    """The member a token names, asked of TACTIC on every request."""
    try:
        result = await tactic.request(
            "GET",
            "/api/v1/members/me",
            headers={"Authorization": authorization},
        )
    except TacticError as exc:
        raise_tactic_http_error(exc)
    return MemberProfile.model_validate(result)


async def _agent(request: Request, authorization: str) -> AgentProfile:
    try:
        result = await tactic.request(
            "GET",
            "/api/v1/agents/me",
            headers={"Authorization": authorization},
        )
    except TacticError as exc:
        raise_tactic_http_error(exc)
    agent = AgentProfile.model_validate(result)
    refusal = agent_refusal(request.scope.get("route"), may_start=agent.may_start)
    if refusal:
        raise HTTPException(403, refusal)
    return agent


async def current_caller(
    request: Request,
    authorization: str = Depends(member_authorization),
) -> MemberProfile | AgentProfile:
    """The signed-in member, or an agent on a route that is open to keys."""
    if is_agent_key(authorization.removeprefix("Bearer ")):
        return await _agent(request, authorization)
    return await signed_in_member(authorization)


async def current_member(
    caller: MemberProfile | AgentProfile = Depends(current_caller),
) -> MemberProfile:
    """A person. A key is refused here even on a route that is open to keys."""
    if isinstance(caller, AgentProfile):
        raise HTTPException(403, "This needs a member, not a key for an agent")
    return caller


async def current_agent(
    caller: MemberProfile | AgentProfile = Depends(current_caller),
) -> AgentProfile:
    if not isinstance(caller, AgentProfile):
        raise HTTPException(403, "Only a key for an agent can ask this")
    return caller


def caller_key(caller: MemberProfile | AgentProfile) -> str:
    """What a rate limit counts a caller by. An agent never shares a member's."""
    prefix = "agent-" if isinstance(caller, AgentProfile) else ""
    return f"{prefix}{caller.id}"


def _refuse_without(
    permission: Permission, caller: MemberProfile | AgentProfile
) -> None:
    # A key has no permissions: the route it calls says what it is open to,
    # and current_caller has checked that.
    if isinstance(caller, AgentProfile):
        return
    if permission not in caller.permissions:
        raise HTTPException(403, f"This needs the {permission} permission")


@cache
def require_permission(permission: Permission):
    """One dependency per permission, so access tests can tell them apart."""

    async def holds_permission(
        caller: MemberProfile | AgentProfile = Depends(current_caller),
    ) -> MemberProfile | AgentProfile:
        _refuse_without(permission, caller)
        return caller

    holds_permission.__name__ = f"require_{permission}"
    return holds_permission


@cache
def writes_require(permission: Permission):
    """Every member reads; changing anything needs ``permission``."""

    async def reads_open_writes_checked(
        request: Request,
        caller: MemberProfile | AgentProfile = Depends(current_caller),
    ) -> None:
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            _refuse_without(permission, caller)

    reads_open_writes_checked.__name__ = f"writes_require_{permission}"
    return reads_open_writes_checked
