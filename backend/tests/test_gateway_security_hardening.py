"""Regressions for gateway client identity, retries, sessions and auth caching."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from off_key_api_gateway.api import access
from off_key_api_gateway.api.rate_limiter import client_ip
from off_key_api_gateway.api.v1 import auth as auth_api
from off_key_api_gateway.facades.tactic import Tactic, TacticError
from off_key_core.schemas.user import UserLogin
from off_key_tactic_middleware.services.data import users as users_module

from tests.support.env import set_auth_env


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


class _FailingSession:
    def __init__(self, error):
        self.error = error
        self.calls = 0

    def request(self, **_):
        self.calls += 1
        raise self.error


@pytest.fixture
def facade(monkeypatch):
    from off_key_core.config.service_auth import get_service_auth_settings

    monkeypatch.setenv("INTERNAL_API_SECRET", "test-private-api-credential-123456789")
    get_service_auth_settings.cache_clear()
    monkeypatch.setattr("off_key_api_gateway.facades.tactic.asyncio.sleep", AsyncMock())
    client = Tactic.__new__(Tactic)
    client.base_url = "http://tactic"
    client._max_retries = 2
    yield client
    get_service_auth_settings.cache_clear()


def _attach(client, error):
    session = _FailingSession(error)
    client._get_session = AsyncMock(return_value=session)
    return session


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
async def test_writes_are_not_repeated_after_the_request_may_have_run(
    facade, method, monkeypatch
):
    set_auth_env(monkeypatch)
    session = _attach(facade, aiohttp.ServerDisconnectedError())
    with pytest.raises(TacticError):
        await facade.request(method, "/api/v1/orchestration/start")
    assert session.calls == 1


@pytest.mark.asyncio
async def test_reads_and_unsent_writes_are_retried(facade, monkeypatch):
    set_auth_env(monkeypatch)
    session = _attach(facade, aiohttp.ServerDisconnectedError())
    with pytest.raises(TacticError):
        await facade.request("GET", "/api/v1/monitors")
    assert session.calls == 3
    refused = aiohttp.ClientConnectorError(
        SimpleNamespace(ssl=None, host="tactic", port=8001), OSError("refused")
    )
    session = _attach(facade, refused)
    with pytest.raises(TacticError):
        await facade.request("POST", "/api/v1/members/invitations")
    assert session.calls == 3


class _RotatingTactic:
    async def request(self, method, endpoint, **kwargs):
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
    monkeypatch.setattr(auth_api, "tactic", _RotatingTactic())
    app = FastAPI()
    app.include_router(auth_api.router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test"
    ) as client:
        client.cookies.set(auth_api.REMEMBERED_SESSION_COOKIE, "r" * 43)
        response = await client.post("/refresh", headers={"X-Off-Key-Session": "1"})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert cookie.startswith(f"{auth_api.REMEMBERED_SESSION_COOKIE}={'n' * 43}")
    assert "Max-Age=1234" in cookie and "HttpOnly" in cookie


@pytest.mark.asyncio
async def test_forgot_password_delivers_mail_after_responding(monkeypatch):
    set_auth_env(monkeypatch)
    order = []

    async def request(*_, **__):
        return {"email": "member@example.com", "token": "t" * 43}

    async def send(email, token):
        order.append("mail")
        raise RuntimeError("SMTP down")

    monkeypatch.setattr(auth_api.tactic, "request", request)
    monkeypatch.setattr(auth_api, "send_password_reset_email", send)
    app = FastAPI()
    app.include_router(auth_api.router)
    app.state.limiter = auth_api.limiter
    auth_api.limiter.reset()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/forgot-password", json={"email": "member@example.com"}
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
    """Removal and deactivation must take effect on the very next request."""
    profile = {
        "id": 17,
        "email": "member@example.com",
        "role": "user",
        "is_active": True,
        "is_verified": True,
        "created_at": datetime.now(UTC).isoformat(),
    }
    remote = AsyncMock(return_value=profile)
    monkeypatch.setattr(access.tactic, "request", remote)
    await access.current_member("Bearer member")
    remote.side_effect = TacticError("Revoked", status=401)
    with pytest.raises(HTTPException):
        await access.current_member("Bearer member")
    assert remote.await_count == 2
