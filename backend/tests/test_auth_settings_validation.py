import pytest
from off_key_core.config.auth import get_auth_settings
from pydantic import ValidationError

from tests.support.env import set_auth_env


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("ALGORITHM", "none"),
        ("JWT_SECRET", "short"),
        ("JWT_SECRET", " " + "z" * 32),
        ("ACCESS_TOKEN_EXPIRE_MINUTES", "0"),
        ("JWT_CLOCK_SKEW_SECONDS", "500"),
    ],
    ids=[
        "unsupported_algorithm",
        "short_secret",
        "padded_secret",
        "zero_expiry",
        "excessive_clock_skew",
    ],
)
def test_auth_settings_reject_unsafe_values(monkeypatch, name, value):
    set_auth_env(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        get_auth_settings()
