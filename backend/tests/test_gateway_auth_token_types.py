import pytest
from off_key_api_gateway.services.auth import create_jwt
from off_key_core.config.auth import get_auth_settings
from off_key_core.schemas.members import AcceptInvitation, PasswordReset
from pydantic import ValidationError


def _set_auth_env(monkeypatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-key-material-123456")
    monkeypatch.setenv("ALGORITHM", "HS256")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    monkeypatch.setenv("SUPERUSER_MAIL", "admin@example.com")
    get_auth_settings.cache_clear()


def test_access_token_cannot_be_used_as_an_account_link(monkeypatch):
    _set_auth_env(monkeypatch)
    token = create_jwt(
        {"sub": "member@example.com", "user_id": 1, "session_version": 0}
    )
    with pytest.raises(ValidationError):
        AcceptInvitation(token=token, password="long-enough-password")
    with pytest.raises(ValidationError):
        PasswordReset(token=token, new_password="long-enough-password")
