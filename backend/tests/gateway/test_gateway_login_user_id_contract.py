"""A login's token carries the member's id and session version."""

from unittest.mock import AsyncMock

import pytest
from jose import jwt
from off_key_api_gateway.providers import (
    get_remembered_session_service,
    get_user_service,
)
from off_key_core.config.auth import get_auth_settings

from tests.support.env import set_auth_env
from tests.support.gateway import gateway_app, returning
from tests.support.http import asgi_client


@pytest.mark.asyncio
async def test_login_includes_server_assigned_id_and_session_version(monkeypatch):
    set_auth_env(monkeypatch)
    users = AsyncMock()
    users.authenticate.return_value = {
        "id": 42,
        "email": "user@example.com",
        "role": "user",
        "session_version": 3,
    }
    app = gateway_app(
        overrides={
            get_user_service: returning(users),
            get_remembered_session_service: returning(AsyncMock()),
        }
    )
    async with asgi_client(app) as client:
        result = await client.post(
            "/v1/auth/login",
            json={"email": "user@example.com", "password": "correct-password"},
        )
    assert result.status_code == 200, result.text
    response = result.json()

    settings = get_auth_settings()
    payload = jwt.decode(
        response["access_token"],
        settings.JWT_SECRET.get_secret_value(),
        algorithms=[settings.ALGORITHM],
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
    )

    assert response["member_id"] == 42
    assert payload["sub"] == "user@example.com"
    assert payload["user_id"] == 42
    assert payload["session_version"] == 3
