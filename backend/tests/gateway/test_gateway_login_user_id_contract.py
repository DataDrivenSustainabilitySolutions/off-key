import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from jose import jwt
from off_key_api_gateway.api.v1 import auth as auth_api
from off_key_core.config.auth import get_auth_settings

from tests.support.env import set_auth_env


class _TacticLoginStub:
    async def authenticate_user(self, *, email: str, password: str):
        return {"id": 42, "email": email, "role": "user", "session_version": 3}


@pytest.mark.asyncio
async def test_login_includes_server_assigned_id_and_session_version(monkeypatch):
    set_auth_env(monkeypatch)
    monkeypatch.setattr(auth_api, "tactic", _TacticLoginStub())

    app = FastAPI()
    app.include_router(auth_api.router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        result = await client.post(
            "/login", json={"email": "user@example.com", "password": "correct-password"}
        )
    assert result.status_code == 200
    response = result.json()

    settings = get_auth_settings()
    payload = jwt.decode(
        response["access_token"],
        settings.JWT_SECRET.get_secret_value(),
        algorithms=[settings.ALGORITHM],
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
    )

    assert response["user_id"] == 42
    assert payload["sub"] == "user@example.com"
    assert payload["user_id"] == 42
    assert payload["session_version"] == 3
