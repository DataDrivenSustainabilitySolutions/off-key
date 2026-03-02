from off_key_api_gateway.services.auth import (
    create_reset_token,
    create_verification_token,
    verify_reset_token,
    verify_verification_token,
)
from off_key_core.config.auth import get_auth_settings


def _set_auth_env(monkeypatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("JWT_VERIFICATION_SECRET", "test-jwt-verification-secret")
    monkeypatch.setenv("ALGORITHM", "HS256")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    monkeypatch.setenv("SUPERUSER_MAIL", "admin@example.com")
    get_auth_settings.cache_clear()


def test_verify_verification_token_accepts_only_verification_tokens(monkeypatch):
    _set_auth_env(monkeypatch)
    email = "user@example.com"

    verification_token = create_verification_token(email)
    reset_token = create_reset_token(email)

    assert verify_verification_token(verification_token) == email
    assert verify_verification_token(reset_token) is None


def test_verify_reset_token_accepts_only_reset_tokens(monkeypatch):
    _set_auth_env(monkeypatch)
    email = "user@example.com"

    verification_token = create_verification_token(email)
    reset_token = create_reset_token(email)

    assert verify_reset_token(reset_token) == email
    assert verify_reset_token(verification_token) is None
