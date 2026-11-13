"""The API accepts only well-formed access tokens it issued."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt
from off_key_api_gateway.api.access import current_caller, signed_in_member
from off_key_api_gateway.api.v1.auth import access_token_response
from off_key_core.config.auth import get_auth_settings

from tests.support.env import set_auth_env


@pytest.fixture(autouse=True)
def auth_env(monkeypatch):
    set_auth_env(monkeypatch)


def signed(**claims):
    settings = get_auth_settings()
    return jwt.encode(
        {
            "sub": "member@example.com",
            "user_id": 7,
            "session_version": 2,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
        }
        | claims,
        settings.JWT_SECRET.get_secret_value(),
        algorithm=settings.ALGORITHM,
    )


async def decode(token, user=None):
    session = SimpleNamespace(scalar=AsyncMock(return_value=user))
    if token is None:
        return await current_caller(SimpleNamespace(), None, session)
    if token.startswith("Bearer "):
        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer", credentials=token.removeprefix("Bearer ")
        )
        return await current_caller(
            SimpleNamespace(state=SimpleNamespace()), credentials, session
        )
    return await signed_in_member(token, session)


async def test_valid_token_resolves_the_current_member():
    user = SimpleNamespace(is_verified=True, is_active=True, session_version=2)
    assert await decode(signed(), user) is user


EXPIRED = {"exp": datetime.now(UTC) - timedelta(hours=1)}


@pytest.mark.parametrize(
    ("claims", "detail"),
    [
        (None, "Sign in to continue"),
        ("not-a-token", "Invalid or expired access token"),
        (EXPIRED, "Invalid or expired access token"),
        ({"aud": "someone-else"}, "Invalid or expired access token"),
        ({"user_id": "7"}, "Invalid access token"),
        ({"user_id": True}, "Invalid access token"),
        ({"user_id": 0}, "Invalid access token"),
        ({"session_version": -1}, "Invalid access token"),
        ({"session_version": 2.0}, "Invalid access token"),
        ({"token_type": "refresh"}, "Invalid access token"),
    ],
)
async def test_malformed_tokens_are_rejected_with_their_reason(claims, detail):
    token = signed(**claims) if isinstance(claims, dict) else claims
    with pytest.raises(HTTPException) as rejected:
        await decode(token)
    assert (rejected.value.status_code, rejected.value.detail) == (401, detail)


async def test_a_stale_session_version_is_rejected():
    user = SimpleNamespace(is_verified=True, is_active=True, session_version=3)
    with pytest.raises(HTTPException) as rejected:
        await decode(signed(), user)
    assert rejected.value.detail == "This session is no longer valid"


async def test_an_issued_token_signs_its_member_in():
    issued = access_token_response(
        {"email": "member@example.com", "id": 7, "session_version": 2}
    )
    assert issued["member_id"] == 7
    user = SimpleNamespace(is_verified=True, is_active=True, session_version=2)
    assert await decode("Bearer " + issued["access_token"], user) is user
