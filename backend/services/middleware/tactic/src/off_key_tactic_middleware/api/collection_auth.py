"""Verify membership against current account state for every protected request."""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from off_key_core.auth.tokens import InvalidAccessToken, decode_access_token
from off_key_core.db.base import get_db_async
from off_key_core.db.models import User
from off_key_core.utils.enum import RoleEnum
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

bearer = HTTPBearer(auto_error=False)


async def current_member(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_db_async),
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
    user = await session.scalar(
        select(User).where(User.id == claims.user_id, User.email == claims.sub)
    )
    if (
        user is None
        or not user.is_verified
        or not user.is_active
        or user.session_version != claims.session_version
    ):
        raise HTTPException(401, "This session is no longer valid")
    return user


async def require_admin(user: User = Depends(current_member)) -> User:
    if user.role != RoleEnum.admin:
        raise HTTPException(403, "Administrator access required")
    return user
