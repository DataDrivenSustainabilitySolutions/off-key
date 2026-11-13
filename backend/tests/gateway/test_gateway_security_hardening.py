"""Regressions for client identity, sessions and per-request access checks."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from off_key_api_gateway.api import access
from off_key_api_gateway.api.rate_limiter import client_ip
from off_key_api_gateway.api.v1 import auth as auth_api
from off_key_api_gateway.providers import (
    get_member_service,
    get_remembered_session_service,
)
from off_key_core.schemas.user import UserLogin
from off_key_tactic_middleware.services.accounts import users as users_module

from tests.support.env import set_auth_env
from tests.support.gateway import gateway_app, member, returning
from tests.support.http import asgi_client
from tests.support.tokens import access_token


def _request(peer, forwarded=None):
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    from starlette.requests import Request

    return Request(
        {"type": "http", "client": (peer, 1234), "headers": headers, "path": "/"}
    )


@pytest.mark.parametrize(
    "peer, forwarded, expected",
    [
        ("203.0.113.5", "198.51.100.1", "203.0.113.5"),
        ("10.0.0.2", None, "10.0.0.2"),
        ("10.0.0.2", "198.51.100.1", "198.51.100.1"),
        ("10.0.0.2", "1.2.3.4, 198.51.100.1, 10.0.0.9", "198.51.100.1"),
        ("10.0.0.2", "garbage, 198.51.100.1", "198.51.100.1"),
        ("10.0.0.2", "10.0.0.3", "10.0.0.3"),
    ],
)
def test_client_ip_uses_the_nearest_untrusted_hop(peer, forwarded, expected):
    assert client_ip(_request(peer, forwarded)) == expected


class _RotatingSessions:
    async def refresh(self, token):
        return {
            "id": 42,
            "email": "member@example.com",
            "session_version": 3,
            "token": "n" * 43,
            "expires_in": 1234,
        }


@pytest.mark.asyncio
async def test_refresh_replaces_the_cookie_without_extending_its_deadline(
    monkeypatch,
):
    set_auth_env(monkeypatch)
    app = gateway_app(
        overrides={get_remembered_session_service: returning(_RotatingSessions())}
    )
    async with asgi_client(app, base_url="https://test") as client:
        client.cookies.set(auth_api.REMEMBERED_SESSION_COOKIE, "r" * 43)
        response = await client.post(
            "/v1/auth/refresh", headers={"X-Off-Key-Session": "1"}
        )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{auth_api.REMEMBERED_SESSION_COOKIE}={'n' * 43}")
    assert "Max-Age=1234" in cookie and "HttpOnly" in cookie


@pytest.mark.asyncio
async def test_password_reset_request_delivers_mail_after_responding(monkeypatch):
    set_auth_env(monkeypatch)
    order = []
    members = AsyncMock()
    members.issue_reset_token.return_value = {
        "email": "member@example.com",
        "token": "t" * 43,
    }

    async def send(email, token):
        order.append("mail")
        raise RuntimeError("SMTP down")

    monkeypatch.setattr(auth_api, "send_password_reset_email", send)
    app = gateway_app(overrides={get_member_service: returning(members)})
    async with asgi_client(app) as client:
        response = await client.post(
            "/v1/auth/password-reset", json={"email": "member@example.com"}
        )
    assert response.status_code == 200
    assert response.json()["message"].startswith("If the email is registered")
    assert order == ["mail"]
    auth_api.limiter.reset()


def test_login_emails_are_normalized():
    login = UserLogin(email="  Alice@Example.COM", password="x")
    assert login.email == "alice@example.com"


@pytest.mark.asyncio
@pytest.mark.parametrize("stored", [None, "!"])
async def test_unknown_and_pending_accounts_pay_the_bcrypt_cost(monkeypatch, stored):
    checks = []
    real = users_module.bcrypt.checkpw

    def spy(password, hashed):
        checks.append(hashed)
        return real(password, hashed)

    monkeypatch.setattr(users_module.bcrypt, "checkpw", spy)
    user = None if stored is None else SimpleNamespace(hashed_password=stored)
    repository = SimpleNamespace(get_by_email=AsyncMock(return_value=user))
    service = users_module.UserService(AsyncMock(), repository)
    with pytest.raises(users_module.AuthenticationError):
        await service.authenticate(email="nobody@example.com", password="guess")
    assert checks == [users_module._DUMMY_HASH.encode()]


@pytest.mark.asyncio
async def test_member_access_is_checked_on_every_request(monkeypatch):
    """Removal and deactivation take effect on the very next request."""
    set_auth_env(monkeypatch)
    signed_in = member(session_version=0)
    token = access_token(signed_in)
    session = AsyncMock()
    session.scalar.return_value = signed_in
    assert await access.signed_in_member(token, session) is signed_in
    signed_in.is_active = False
    with pytest.raises(HTTPException) as refused:
        await access.signed_in_member(token, session)
    assert refused.value.status_code == 401
    session.scalar.return_value = None
    with pytest.raises(HTTPException):
        await access.signed_in_member(token, session)
    assert session.scalar.await_count == 3
