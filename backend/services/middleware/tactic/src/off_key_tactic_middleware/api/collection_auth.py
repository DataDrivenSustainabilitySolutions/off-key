"""Verify the existing access token at the collection control boundary."""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from off_key_core.config.auth import get_auth_settings
from off_key_core.db.base import get_db_async
from off_key_core.db.models import User
from off_key_core.utils.enum import RoleEnum
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

bearer = HTTPBearer(auto_error=False)


async def collection_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_db_async),
) -> User:
    if credentials is None:
        raise HTTPException(401, "Sign in to view data sources")
    settings = get_auth_settings()
    try:
        claims = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET.get_secret_value(),
            algorithms=[settings.ALGORITHM],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
            options={
                "require_exp": True,
                "require_sub": True,
                "require_iss": True,
                "require_aud": True,
                "leeway": settings.JWT_CLOCK_SKEW_SECONDS,
            },
        )
    except JWTError as exc:
        raise HTTPException(401, "Invalid or expired access token") from exc
    user_id = claims.get("user_id")
    if type(user_id) is not int or claims.get("token_type") is not None:
        raise HTTPException(401, "Invalid access token")
    user = await session.scalar(
        select(User).where(User.id == user_id, User.email == claims["sub"])
    )
    if user is None or not user.is_verified:
        raise HTTPException(403, "A verified account is required")
    return user


async def collection_admin(user: User = Depends(collection_user)) -> User:
    if user.role != RoleEnum.admin:
        raise HTTPException(403, "Only administrators can configure collection")
    return user
