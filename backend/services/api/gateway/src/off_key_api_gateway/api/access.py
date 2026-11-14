"""Who is calling, checked against the account as it is now on every request.

A caller is a member with a token, or an agent with a key. A key is refused on
every route that does not open itself to keys.
"""

from functools import cache

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from off_key_core.auth.agents import (
    AGENT_KEY_PREFIX,
    agent_key_digest,
    agent_refusal,
    is_agent_key,
)
from off_key_core.auth.demo import DEMO_VIEWER_PERMISSIONS, DEMO_VIEWER_ROLE
from off_key_core.auth.permissions import Permission
from off_key_core.auth.tokens import (
    InvalidAccessToken,
    access_token_digest,
    decode_access_token,
)
from off_key_core.db.models import Agent, RememberedSession, RevokedAccessToken, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..providers import RequestSession

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


async def signed_in_member(token: str, session: AsyncSession) -> User:
    """The member a token names, checked against the account as it is now."""
    try:
        claims = decode_access_token(token)
    except InvalidAccessToken as exc:
        detail = (
            "Invalid or expired access token"
            if exc.kind == "token"
            else "Invalid access token"
        )
        raise HTTPException(401, detail) from exc
    statement = select(User).where(
        User.id == claims.user_id,
        User.email == claims.sub,
        ~select(RevokedAccessToken.token_hash)
        .where(RevokedAccessToken.token_hash == access_token_digest(token))
        .exists(),
    )
    if claims.session_family is not None:
        statement = statement.where(
            select(RememberedSession.token_hash)
            .where(
                RememberedSession.family_id == claims.session_family,
                RememberedSession.user_id == claims.user_id,
            )
            .exists()
        )
    user = await session.scalar(statement)
    if (
        user is None
        or not user.is_verified
        or not user.is_active
        or user.session_version != claims.session_version
    ):
        raise HTTPException(401, "This session is no longer valid")
    return user


async def agent_by_key(key: str, session: AsyncSession) -> Agent | None:
    """The agent holding a key; a revoked key names nobody."""
    return await session.scalar(
        select(Agent).where(Agent.key_hash == agent_key_digest(key))
    )


async def current_caller(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = RequestSession,
) -> User | Agent:
    """The signed-in member, or an agent on a route that is open to keys."""
    if credentials is None:
        raise HTTPException(401, "Sign in to continue")
    if is_agent_key(credentials.credentials):
        agent = await agent_by_key(credentials.credentials, session)
        if agent is None:
            raise HTTPException(401, "This key is not valid")
        refusal = agent_refusal(request.scope.get("route"), starts=agent.starts)
        if refusal:
            raise HTTPException(403, refusal)
        return agent
    member = await signed_in_member(credentials.credentials, session)
    if getattr(request.state, "demo_guest", False) and (
        member.role != DEMO_VIEWER_ROLE
        or set(member.permissions) != DEMO_VIEWER_PERMISSIONS
    ):
        # A guest browses as the demo viewer. Its role and permissions are
        # checked on every request, even while the viewer's token is cached.
        raise HTTPException(503, "The public demo is unavailable right now.")
    return member


async def current_member(caller: User | Agent = Depends(current_caller)) -> User:
    """A person. A key is refused here even on a route that is open to keys."""
    if isinstance(caller, Agent):
        raise HTTPException(403, "This needs a member, not a key for an agent")
    return caller


async def current_agent(caller: User | Agent = Depends(current_caller)) -> Agent:
    if not isinstance(caller, Agent):
        raise HTTPException(403, "Only a key for an agent can ask this")
    return caller


def member_id(caller: User | Agent) -> int | None:
    """Who a record names as its creator. An agent is not a member, so none."""
    return None if isinstance(caller, Agent) else caller.id


def caller_key(caller: User | Agent) -> str:
    """What a rate limit counts a caller by. An agent never shares a member's."""
    prefix = "agent-" if isinstance(caller, Agent) else ""
    return f"{prefix}{caller.id}"


def _refuse_without(permission: Permission, caller: User | Agent) -> None:
    # A key has no permissions: the route it calls says what it is open to,
    # and current_caller has checked that.
    if isinstance(caller, Agent):
        return
    if permission not in caller.permissions:
        raise HTTPException(403, f"This needs the {permission} permission")


@cache
def require_permission(permission: Permission):
    """One dependency per permission, so access tests can tell them apart."""

    async def holds_permission(
        caller: User | Agent = Depends(current_caller),
    ) -> User | Agent:
        _refuse_without(permission, caller)
        return caller

    holds_permission.__name__ = f"require_{permission}"
    return holds_permission


@cache
def writes_require(permission: Permission):
    """Every member reads; changing anything needs ``permission``."""

    async def reads_open_writes_checked(
        request: Request,
        caller: User | Agent = Depends(current_caller),
    ) -> None:
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            _refuse_without(permission, caller)

    reads_open_writes_checked.__name__ = f"writes_require_{permission}"
    return reads_open_writes_checked
