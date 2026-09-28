from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt
from off_key_api_gateway.api.v1 import auth as gateway_auth
from off_key_core.config.auth import get_auth_settings
from off_key_core.db.models import User
from off_key_core.utils.enum import RoleEnum
from off_key_tactic_middleware.api.collection_auth import (
    current_member,
    require_admin,
)

from .test_gateway_auth_token_types import _set_auth_env


@pytest.mark.asyncio
async def test_public_registration_is_closed():
    with pytest.raises(HTTPException) as denied:
        await gateway_auth.register()
    assert denied.value.status_code == 403


@pytest.mark.asyncio
async def test_collection_uses_verified_user_and_current_database_role(monkeypatch):
    _set_auth_env(monkeypatch)
    settings = get_auth_settings()
    claims = {
        "sub": "user@example.com",
        "user_id": 1,
        "session_version": 0,
        "role": "admin",
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
    }

    def credentials(data):
        return HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=jwt.encode(
                data,
                settings.JWT_SECRET.get_secret_value(),
                algorithm="HS256",
            ),
        )

    user = User(
        id=1,
        email=claims["sub"],
        is_verified=True,
        is_active=True,
        session_version=0,
        role=RoleEnum.user,
    )
    session = AsyncMock()
    session.scalar.return_value = user
    assert await current_member(credentials(claims), session) is user
    with pytest.raises(HTTPException) as forbidden:
        await require_admin(user)
    assert forbidden.value.status_code == 403
    user.is_verified = False
    with pytest.raises(HTTPException) as unverified:
        await current_member(credentials(claims), session)
    assert unverified.value.status_code == 401
    for invalid in (
        {**claims, "exp": datetime.now(UTC) - timedelta(minutes=5)},
        {**claims, "aud": "other-app"},
        {**claims, "token_type": "verification"},
        {**claims, "user_id": True},
        {**claims, "session_version": True},
        {**claims, "session_version": -1},
        {key: value for key, value in claims.items() if key != "session_version"},
    ):
        with pytest.raises(HTTPException) as denied:
            await current_member(credentials(invalid), session)
        assert denied.value.status_code == 401
