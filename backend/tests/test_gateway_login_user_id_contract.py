import pytest
from jose import jwt

from off_key_api_gateway.api.v1 import auth as auth_api
from off_key_core.config.auth import get_auth_settings
from off_key_core.schemas.user import UserLogin


def _set_auth_env(monkeypatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-key-material-123456")
    monkeypatch.setenv("JWT_VERIFICATION_SECRET", "test-jwt-verification-secret-654321")
    monkeypatch.setenv("ALGORITHM", "HS256")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    monkeypatch.setenv("SUPERUSER_MAIL", "admin@example.com")
    get_auth_settings.cache_clear()


class _LegacyTacticLoginStub:
    async def authenticate_user(self, *, email: str, password: str):
        return {"email": email, "role": "user"}

    async def get_user_by_email(self, email: str):
        return {"id": 42, "email": email, "role": "user", "is_verified": True}


@pytest.mark.asyncio
async def test_login_resolves_user_id_when_tactic_login_omits_it(monkeypatch):
    _set_auth_env(monkeypatch)
    monkeypatch.setattr(auth_api, "tactic", _LegacyTacticLoginStub())

    response = await auth_api.login(
        UserLogin(email="user@example.com", password="correct-password")
    )

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
