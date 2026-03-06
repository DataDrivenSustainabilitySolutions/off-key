import pytest
from pydantic import ValidationError

from off_key_core.config.auth import get_auth_settings


@pytest.fixture
def auth_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "a" * 32)
    monkeypatch.setenv("JWT_VERIFICATION_SECRET", "b" * 32)
    monkeypatch.setenv("ALGORITHM", "HS256")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    monkeypatch.setenv("SUPERUSER_MAIL", "admin@example.com")
    get_auth_settings.cache_clear()
    yield
    get_auth_settings.cache_clear()


def test_auth_settings_rejects_unsupported_algorithm(monkeypatch, auth_env):
    monkeypatch.setenv("ALGORITHM", "none")
    get_auth_settings.cache_clear()

    with pytest.raises(ValidationError):
        get_auth_settings()


def test_auth_settings_rejects_short_jwt_secret(monkeypatch, auth_env):
    monkeypatch.setenv("JWT_SECRET", "short")
    get_auth_settings.cache_clear()

    with pytest.raises(ValidationError):
        get_auth_settings()


def test_auth_settings_rejects_identical_jwt_secrets(monkeypatch, auth_env):
    same_secret = "z" * 32
    monkeypatch.setenv("JWT_SECRET", same_secret)
    monkeypatch.setenv("JWT_VERIFICATION_SECRET", same_secret)
    get_auth_settings.cache_clear()

    with pytest.raises(ValidationError):
        get_auth_settings()


def test_auth_settings_rejects_invalid_expiry(monkeypatch, auth_env):
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "0")
    get_auth_settings.cache_clear()

    with pytest.raises(ValidationError):
        get_auth_settings()


def test_auth_settings_rejects_invalid_clock_skew(monkeypatch, auth_env):
    monkeypatch.setenv("JWT_CLOCK_SKEW_SECONDS", "500")
    get_auth_settings.cache_clear()

    with pytest.raises(ValidationError):
        get_auth_settings()
