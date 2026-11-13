"""Verify the caller against current account state for every protected request.

A caller is a member with a token, or an agent with a key. A key is refused on
every route that does not open itself to keys.
"""

from functools import cache

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from off_key_core.auth.agents import agent_key_digest, agent_refusal, is_agent_key
from off_key_core.auth.permissions import Permission
from off_key_core.auth.tokens import (
    InvalidAccessToken,
    access_token_digest,
    decode_access_token,
)
from off_key_core.db.models import Agent, RememberedSession, RevokedAccessToken, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..provider import RequestSession

bearer = HTTPBearer(auto_error=False)


async def signed_in_member(
    credentials: HTTPAuthorizationCredentials | None, session: AsyncSession
) -> User:
    """The member a token names, checked against the account as it is now."""
    if credentials is None:
        raise HTTPException(401, "Sign in to continue")
    token = credentials.credentials
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


async def _agent(request: Request, key: str, session: AsyncSession) -> Agent:
    agent = await session.scalar(
        select(Agent).where(Agent.key_hash == agent_key_digest(key))
    )
    if agent is None:
        raise HTTPException(401, "This key is not valid")
    refusal = agent_refusal(request.scope.get("route"), may_start=agent.may_start)
    if refusal:
        raise HTTPException(403, refusal)
    return agent


async def current_caller(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = RequestSession,
) -> User | Agent:
    """The signed-in member, or an agent on a route that is open to keys."""
    if credentials is not None and is_agent_key(credentials.credentials):
        return await _agent(request, credentials.credentials, session)
    return await signed_in_member(credentials, session)


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


@cache
def require_permission(permission: Permission):
    """One dependency per permission, so access tests can tell them apart."""

    async def holds_permission(
        caller: User | Agent = Depends(current_caller),
    ) -> User | Agent:
        # A key has no permissions: the route it calls says what it is open to,
        # and current_caller has checked that.
        if not isinstance(caller, Agent) and permission not in caller.permissions:
            raise HTTPException(403, f"This needs the {permission} permission")
        return caller

    holds_permission.__name__ = f"require_{permission}"
    return holds_permission
