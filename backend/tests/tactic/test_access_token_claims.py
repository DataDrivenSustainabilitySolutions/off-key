"""TACTIC accepts only well-formed access tokens issued by the gateway."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from jose import jwt
from off_key_api_gateway.api.v1.auth import access_token_response
from off_key_core.config.auth import get_auth_settings
from off_key_tactic_middleware.api.collection_auth import current_member

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
    credentials = (
        None
        if token is None
        else HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    )
    return await current_member(credentials, session)


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


@pytest.mark.parametrize(
    ("authenticated", "detail"),
    [
        ({"id": "7", "session_version": 0}, "returned an invalid user id"),
        ({"id": 0, "session_version": 0}, "returned an invalid user id"),
        ({"id": True, "session_version": 0}, "returned an invalid user id"),
        ({"id": 7, "session_version": None}, "returned an invalid session"),
        ({"id": 7, "session_version": -1}, "returned an invalid session"),
    ],
)
def test_gateway_refuses_to_sign_an_invalid_authentication_result(
    authenticated, detail
):
    with pytest.raises(HTTPException) as refused:
        access_token_response({"email": "member@example.com", **authenticated})
    assert refused.value.status_code == 502
    assert detail in refused.value.detail


async def test_gateway_issued_token_round_trips_through_tactic():
    issued = access_token_response(
        {"email": "member@example.com", "id": 7, "session_version": 2}
    )
    assert issued["user_id"] == 7
    user = SimpleNamespace(is_verified=True, is_active=True, session_version=2)
    assert await decode(issued["access_token"], user) is user
