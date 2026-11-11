"""Verify membership against current account state for every protected request."""

from functools import cache

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from off_key_core.auth.permissions import Permission
from off_key_core.auth.tokens import (
    InvalidAccessToken,
    access_token_digest,
    decode_access_token,
)
from off_key_core.db.models import RememberedSession, RevokedAccessToken, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..provider import RequestSession

bearer = HTTPBearer(auto_error=False)


async def current_member(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = RequestSession,
) -> User:
    if credentials is None:
        raise HTTPException(401, "Sign in to continue")
    try:
        claims = decode_access_token(credentials.credentials)
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
        .where(
            RevokedAccessToken.token_hash
            == access_token_digest(credentials.credentials)
        )
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


@cache
def require_permission(permission: Permission):
    """One dependency per permission, so access tests can tell them apart."""

    async def holds_permission(user: User = Depends(current_member)) -> User:
        if permission not in user.permissions:
            raise HTTPException(403, f"This needs the {permission} permission")
        return user

    holds_permission.__name__ = f"require_{permission}"
    return holds_permission
