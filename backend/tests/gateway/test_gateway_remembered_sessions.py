from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from jose import jwt
from off_key_api_gateway.api.v1 import auth as auth_api
from off_key_api_gateway.facades.tactic import TacticError
from off_key_core.config.auth import get_auth_settings

from tests.support.env import set_auth_env
from tests.support.http import asgi_client

TOKEN = "r" * 43
COOKIE = auth_api.REMEMBERED_SESSION_COOKIE
HEADERS = {"X-Off-Key-Session": "1"}
LOGIN = {"email": "member@example.com", "password": "synthetic-test-password"}


class SessionTactic:
    def __init__(self):
        self.calls = []
        self.failure = None

    async def authenticate_user(self, *, email, password):
        return {"id": 42, "email": email, "role": "user", "session_version": 3}

    async def request(self, method, endpoint, **kwargs):
        self.calls.append((endpoint, kwargs))
        if self.failure:
            raise TacticError("Session unavailable", status=self.failure)
        if endpoint.endswith("/refresh"):
            return {"id": 42, "email": LOGIN["email"], "session_version": 3}
        return {"token": TOKEN}


@pytest.fixture
def session_api(monkeypatch):
    set_auth_env(monkeypatch)
    tactic = SessionTactic()
    monkeypatch.setattr(auth_api, "tactic", tactic)
    app = FastAPI()
    app.include_router(auth_api.router)
    return app, tactic


def assert_short_access_token(response):
    settings = get_auth_settings()
    claims = jwt.decode(
        response.json()["access_token"],
        settings.JWT_SECRET.get_secret_value(),
        algorithms=[settings.ALGORITHM],
        issuer=settings.JWT_ISSUER,
        audience=settings.JWT_AUDIENCE,
    )
    assert claims["user_id"] == 42
    assert claims["session_version"] == 3
    assert 29 * 60 < claims["exp"] - datetime.now(UTC).timestamp() <= 30 * 60


@pytest.mark.asyncio
async def test_remembered_login_sets_cookie_and_renews_short_access_token(session_api):
    app, tactic = session_api
    async with asgi_client(app, base_url="https://test") as client:
        response = await client.post("/login", json=LOGIN | {"remember_me": True})
        assert response.status_code == 200
        assert_short_access_token(response)
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
        assert "Max-Age=2592000" in cookie and "Path=/" in cookie
        assert response.headers["cache-control"] == "no-store"
        assert "token" not in response.json()
        response = await client.post("/refresh", headers=HEADERS)
        assert response.status_code == 200
        assert_short_access_token(response)
        assert response.headers["cache-control"] == "no-store"
        assert "set-cookie" not in response.headers  # Never extend the 30-day deadline.
        assert tactic.calls[-1][1]["json_data"] == {"token": TOKEN}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "base_url, secure",
    [("http://localhost", False), ("http://public.example.com", True)],
)
async def test_cookie_security_accommodates_only_loopback_http(
    session_api, base_url, secure
):
    app, _ = session_api
    async with asgi_client(app, base_url=base_url) as client:
        response = await client.post("/login", json=LOGIN | {"remember_me": True})
        assert ("Secure" in response.headers["set-cookie"]) is secure


@pytest.mark.asyncio
async def test_unchecked_login_ends_previous_remembered_session(session_api):
    app, tactic = session_api
    async with asgi_client(app, base_url="https://test") as client:
        await client.post("/login", json=LOGIN | {"remember_me": True})
        tactic.calls.clear()
        response = await client.post("/login", json=LOGIN)
        assert response.status_code == 200
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert tactic.calls == [
            ("/api/v1/members/sessions/revoke", {"json_data": {"token": TOKEN}})
        ]
        assert COOKIE not in client.cookies


@pytest.mark.asyncio
@pytest.mark.parametrize("cookie", [None, "malformed", "a" * 44])
async def test_invalid_or_missing_cookie_requires_login(session_api, cookie):
    app, tactic = session_api
    async with asgi_client(app, base_url="https://test") as client:
        if cookie:
            client.cookies.set(COOKIE, cookie)
        response = await client.post("/refresh", headers=HEADERS)
        assert response.status_code == 401
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert not tactic.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [401, 503])
async def test_refresh_only_clears_cookie_on_definitive_rejection(session_api, failure):
    app, tactic = session_api
    tactic.failure = failure
    async with asgi_client(app, base_url="https://test") as client:
        client.cookies.set(COOKIE, TOKEN)
        response = await client.post("/refresh", headers=HEADERS)
        assert response.status_code == failure
        assert ("set-cookie" in response.headers) is (failure == 401)


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", ["/refresh", "/logout"])
async def test_cookie_endpoints_reject_simple_cross_origin_requests(
    session_api, endpoint
):
    app, tactic = session_api
    async with asgi_client(app, base_url="https://test") as client:
        client.cookies.set(COOKIE, TOKEN)
        response = await client.post(endpoint)
        assert response.status_code == 403
        assert not tactic.calls


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, 503])
async def test_logout_revokes_and_always_clears_browser_cookie(session_api, failure):
    app, tactic = session_api
    tactic.failure = failure
    async with asgi_client(app, base_url="https://test") as client:
        client.cookies.set(COOKIE, TOKEN)
        response = await client.post("/logout", headers=HEADERS)
        assert response.status_code == (503 if failure else 200)
        assert "Max-Age=0" in response.headers["set-cookie"]
        assert tactic.calls[-1][0].endswith("/revoke")
