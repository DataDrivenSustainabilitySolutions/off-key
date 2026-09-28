from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt
from off_key_api_gateway.api.v1 import auth as gateway_auth
from off_key_core.config.auth import get_auth_settings
from off_key_core.db.models import User
from off_key_core.schemas.user import UserCreate
from off_key_core.utils.enum import RoleEnum
from off_key_tactic_middleware.api.collection_auth import (
    collection_admin,
    collection_user,
)

from .test_gateway_auth_token_types import _set_auth_env


@pytest.mark.parametrize(
    "email,expected_role",
    [
        ("user@example.com", "user"),
        ("admin@example.com", "admin"),
    ],
)
@pytest.mark.asyncio
async def test_registration_role_is_server_assigned(monkeypatch, email, expected_role):
    _set_auth_env(monkeypatch)
    monkeypatch.setattr(
        gateway_auth.tactic, "get_user_by_email", AsyncMock(return_value=None)
    )
    create = AsyncMock()
    monkeypatch.setattr(gateway_auth.tactic, "create_user", create)
    monkeypatch.setattr(gateway_auth, "send_verification_email", AsyncMock())
    await gateway_auth.register(
        UserCreate.model_validate(
            {
                "email": email,
                "password": "TestPassword123!",
                "role": "admin",
            }
        )
    )
    assert create.call_args.args[0]["role"] == expected_role


@pytest.mark.asyncio
async def test_collection_uses_verified_user_and_current_database_role(monkeypatch):
    _set_auth_env(monkeypatch)
    settings = get_auth_settings()
    claims = {
        "sub": "user@example.com",
        "user_id": 1,
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

    user = User(id=1, email=claims["sub"], is_verified=True, role=RoleEnum.user)
    session = AsyncMock()
    session.scalar.return_value = user
    assert await collection_user(credentials(claims), session) is user
    with pytest.raises(HTTPException) as forbidden:
        await collection_admin(user)
    assert forbidden.value.status_code == 403
    user.is_verified = False
    with pytest.raises(HTTPException) as unverified:
        await collection_user(credentials(claims), session)
    assert unverified.value.status_code == 403
    for invalid in (
        {**claims, "exp": datetime.now(UTC) - timedelta(minutes=5)},
        {**claims, "aud": "other-app"},
        {**claims, "token_type": "verification"},
        {**claims, "user_id": True},
    ):
        with pytest.raises(HTTPException) as denied:
            await collection_user(credentials(invalid), session)
        assert denied.value.status_code == 401
