import pytest
from off_key_api_gateway.services.auth import create_jwt
from off_key_core.schemas.members import AcceptInvitation, PasswordReset
from pydantic import ValidationError

from tests.support.env import set_auth_env


def test_access_token_cannot_be_used_as_an_account_link(monkeypatch):
    set_auth_env(monkeypatch)
    token = create_jwt(
        {"sub": "member@example.com", "user_id": 1, "session_version": 0}
    )
    with pytest.raises(ValidationError):
        AcceptInvitation(token=token, password="long-enough-password")
    with pytest.raises(ValidationError):
        PasswordReset(token=token, new_password="long-enough-password")
