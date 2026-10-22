from types import SimpleNamespace

import bcrypt
import pytest
from off_key_tactic_middleware.domain import AuthenticationError
from off_key_tactic_middleware.services.accounts.users import UserService

PASSWORD = "correct-password"
PASSWORD_HASH = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()


class _UserRepositoryStub:
    def __init__(self, user):
        self._user = user

    async def get_by_email(self, *, email: str):
        if self._user.email == email:
            return self._user
        return None


def _service(**overrides) -> UserService:
    user = SimpleNamespace(
        **{
            "id": 42,
            "email": "user@example.com",
            "hashed_password": PASSWORD_HASH,
            "is_verified": True,
            "is_active": True,
            "session_version": 3,
            "role": "user",
            **overrides,
        }
    )
    return UserService(session=None, repository=_UserRepositoryStub(user))


@pytest.mark.asyncio
async def test_authenticate_returns_numeric_user_id_for_token_claim():
    authenticated_user = await _service().authenticate(
        email="user@example.com", password=PASSWORD
    )

    assert authenticated_user == {
        "id": 42,
        "email": "user@example.com",
        "role": "user",
        "session_version": 3,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"hashed_password": "not-a-bcrypt-hash"}, "Invalid credentials"),
        (
            {"hashed_password": bcrypt.hashpw(b"other", bcrypt.gensalt(4)).decode()},
            "Invalid credentials",
        ),
        ({"hashed_password": "$2b$12$corrupted-hash"}, "Invalid credentials"),
        ({"is_active": False}, "Invalid credentials"),
        ({"is_verified": False}, "Email not verified"),
    ],
    ids=["malformed", "incorrect", "corrupted", "inactive", "unverified"],
)
async def test_authentication_rejects_unusable_credentials_or_accounts(
    overrides, message
):
    with pytest.raises(AuthenticationError, match=message):
        await _service(**overrides).authenticate(
            email="user@example.com", password=PASSWORD
        )
