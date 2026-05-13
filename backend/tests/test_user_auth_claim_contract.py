from types import SimpleNamespace

import bcrypt
import pytest

from off_key_tactic_middleware.services.data.users import UserService


class _UserRepositoryStub:
    def __init__(self, user):
        self._user = user

    async def get_by_email(self, *, email: str):
        if self._user.email == email:
            return self._user
        return None


@pytest.mark.asyncio
async def test_authenticate_returns_numeric_user_id_for_token_claim():
    password = "correct-password"
    hashed_password = bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")
    user = SimpleNamespace(
        id=42,
        email="user@example.com",
        hashed_password=hashed_password,
        is_verified=True,
        role="user",
    )

    service = UserService(session=None, repository=_UserRepositoryStub(user))

    authenticated_user = await service.authenticate(
        email="user@example.com",
        password=password,
    )

    assert authenticated_user["id"] == 42
    assert authenticated_user["email"] == "user@example.com"
