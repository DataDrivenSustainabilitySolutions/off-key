from datetime import datetime, timedelta, timezone

from jose import jwt

from off_key_api_gateway.services.auth import (
    create_reset_token,
    create_verification_token,
    verify_reset_token,
    verify_verification_token,
)
from off_key_core.config.auth import get_auth_settings


def _set_auth_env(monkeypatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-jwt-secret-key-material-123456")
    monkeypatch.setenv("JWT_VERIFICATION_SECRET", "test-jwt-verification-secret-654321")
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


def test_verify_verification_token_rejects_missing_required_claims(monkeypatch):
    _set_auth_env(monkeypatch)
    settings = get_auth_settings()
    token = jwt.encode(
        {
            "sub": "user@example.com",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
        },
        settings.JWT_VERIFICATION_SECRET.get_secret_value(),
        algorithm=settings.ALGORITHM,
    )

    assert verify_verification_token(token) is None


def test_verify_reset_token_rejects_wrong_audience(monkeypatch):
    _set_auth_env(monkeypatch)
    settings = get_auth_settings()
    token = jwt.encode(
        {
            "sub": "user@example.com",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            "iss": settings.JWT_ISSUER,
            "aud": "unexpected-audience",
            "token_type": "password_reset",
        },
        settings.JWT_VERIFICATION_SECRET.get_secret_value(),
        algorithm=settings.ALGORITHM,
    )

    assert verify_reset_token(token) is None
