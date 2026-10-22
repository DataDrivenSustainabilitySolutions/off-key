"""HTTP regressions for the public gateway and private TACTIC trust boundaries."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from off_key_api_gateway.api import access
from off_key_api_gateway.api.rate_limiter import limiter
from off_key_api_gateway.api.v1 import auth, favorites, monitors
from off_key_api_gateway.facades.tactic import TacticError
from off_key_core.config.service_auth import get_service_auth_settings
from off_key_core.schemas.members import AcceptInvitation
from off_key_tactic_middleware.main import create_app
from pydantic import ValidationError

from tests.support.gateway import gateway_app, member_profile
from tests.support.http import asgi_client

PROFILE = member_profile(email="member@example.com")


@pytest.fixture
def gateway():
    yield gateway_app()
    limiter.reset()


@pytest.mark.asyncio
async def test_anonymous_and_invalid_tokens_cannot_reach_business_handlers(
    gateway, monkeypatch
):
    remote = AsyncMock(side_effect=TacticError("Invalid token", status=401))
    monkeypatch.setattr(access.tactic, "request", remote)
    paths = (
        "/chargers/available",
        "/telemetry/example/type",
        "/monitors/all",
        "/favorites?user_id=99",
        "/anomalies/count",
        "/system",
        "/members",
    )
    async with asgi_client(gateway) as client:
        for path in paths:
            assert (await client.get("/v1" + path)).status_code == 401
        remote.assert_not_awaited()
        for path in paths:
            assert (
                await client.get(
                    "/v1" + path, headers={"Authorization": "Bearer invalid"}
                )
            ).status_code == 401


@pytest.mark.asyncio
async def test_members_can_read_and_favorite_only_for_themselves(gateway, monkeypatch):
    gateway.dependency_overrides[access.current_member] = lambda: PROFILE
    get = AsyncMock(return_value=["charger-1"])
    add = AsyncMock(return_value={"message": "Added"})
    monkeypatch.setattr(favorites.tactic, "get_user_favorites", get)
    monkeypatch.setattr(favorites.tactic, "add_user_favorite", add)
    async with asgi_client(gateway) as client:
        response = await client.get("/v1/favorites?user_id=99")
        assert response.json() == ["charger-1"]
        get.assert_awaited_once_with(user_id=17)
        assert (
            await client.post(
                "/v1/favorites", json={"charger_id": "charger-1", "user_id": 99}
            )
        ).status_code == 422
        add.assert_not_awaited()
        assert (
            await client.post("/v1/favorites", json={"charger_id": "charger-1"})
        ).status_code == 200
        add.assert_awaited_once_with(user_id=17, charger_id="charger-1")
        for method, path in (
            ("DELETE", "/members/19"),
            ("POST", "/monitors/start"),
            ("DELETE", "/monitors/example"),
            ("POST", "/anomalies"),
            ("DELETE", "/anomalies/example"),
            ("GET", "/members"),
            ("POST", "/members/invitations"),
            ("PUT", "/members/19"),
        ):
            assert (
                await client.request(
                    method,
                    "/v1" + path,
                    headers={"Authorization": "Bearer member"},
                    json={},
                )
            ).status_code == 403


@pytest.mark.asyncio
async def test_admin_can_manage_monitors(gateway, monkeypatch):
    gateway.dependency_overrides[access.current_member] = lambda: PROFILE.model_copy(
        update={"role": "admin"}
    )
    delete = AsyncMock(return_value={"status": "deleted"})
    monkeypatch.setattr(monitors.tactic, "delete_radar_service", delete)
    async with asgi_client(gateway) as client:
        response = await client.delete("/v1/monitors/example")
    assert response.status_code == 200
    delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_tactic_grants_no_cross_origin_access(monkeypatch):
    """Browsers reach TACTIC only through the gateway, which owns CORS."""
    monkeypatch.setenv("INTERNAL_API_SECRET", "test-private-api-credential-123456789")
    async with asgi_client(create_app()) as client:
        response = await client.get(
            "/health", headers={"Origin": "https://evil.example"}
        )
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.asyncio
async def test_tactic_rejects_direct_business_requests_without_service_credential(
    monkeypatch,
):
    monkeypatch.setenv("INTERNAL_API_SECRET", "test-private-api-credential-123456789")
    get_service_auth_settings.cache_clear()
    app = create_app()
    async with asgi_client(app) as client:
        assert (await client.get("/health")).status_code == 200
        for method, path in (
            ("DELETE", "/api/v1/members/19"),
            ("GET", "/api/v1/data/chargers"),
            ("GET", "/api/v1/data/users/17/favorites"),
            ("POST", "/api/v1/data/auth/login"),
            ("GET", "/api/v1/system"),
            ("GET", "/api/v1/members/me"),
        ):
            assert (await client.request(method, path, json={})).status_code == 401
            assert (
                await client.request(
                    method, path, headers={"X-Off-Key-Service-Key": "wrong"}, json={}
                )
            ).status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [204, 404, 409])
async def test_admin_member_removal_forwards_identity_and_preserves_status(
    gateway, monkeypatch, status
):
    from off_key_api_gateway.api.v1 import members

    gateway.dependency_overrides[access.current_member] = lambda: PROFILE.model_copy(
        update={"role": "admin"}
    )
    remote = AsyncMock(return_value="")
    if status != 204:
        remote.side_effect = TacticError("Cannot remove member", status=status)
    monkeypatch.setattr(members.tactic, "request", remote)
    async with asgi_client(gateway) as client:
        response = await client.delete(
            "/v1/members/19", headers={"Authorization": "Bearer administrator"}
        )
    assert response.status_code == status
    if status == 204:
        assert response.content == b""
    remote.assert_awaited_once_with(
        "DELETE",
        "/api/v1/members/19",
        json_data=None,
        headers={"Authorization": "Bearer administrator"},
    )


@pytest.mark.asyncio
async def test_anonymous_member_removal_cannot_reach_tactic(gateway, monkeypatch):
    remote = AsyncMock()
    monkeypatch.setattr(access.tactic, "request", remote)
    async with asgi_client(gateway) as client:
        assert (await client.delete("/v1/members/19")).status_code == 401
    remote.assert_not_awaited()


@pytest.mark.asyncio
async def test_password_reset_does_not_disclose_membership_and_login_is_limited(
    gateway, monkeypatch
):
    reset = AsyncMock(side_effect=[None, {"email": PROFILE.email, "token": "x" * 43}])
    monkeypatch.setattr(auth.tactic, "request", reset)
    monkeypatch.setattr(auth, "send_password_reset_email", AsyncMock())
    authenticate = AsyncMock(side_effect=TacticError("Invalid credentials", status=401))
    monkeypatch.setattr(auth.tactic, "authenticate_user", authenticate)
    async with asgi_client(gateway) as client:
        missing = await client.post(
            "/v1/auth/forgot-password", json={"email": "missing@example.com"}
        )
        present = await client.post(
            "/v1/auth/forgot-password", json={"email": PROFILE.email}
        )
        assert missing.status_code == present.status_code == 200
        assert missing.json() == present.json()
        for _ in range(10):
            assert (
                await client.post(
                    "/v1/auth/login",
                    json={"email": PROFILE.email, "password": "incorrect"},
                )
            ).status_code == 401
        assert (
            await client.post(
                "/v1/auth/login", json={"email": PROFILE.email, "password": "incorrect"}
            )
        ).status_code == 429


@pytest.mark.parametrize("password", ["short", "é" * 37])
def test_new_passwords_enforce_length_without_bcrypt_truncation(password):
    with pytest.raises(ValidationError):
        AcceptInvitation(token="t" * 43, password=password)


@pytest.mark.asyncio
async def test_path_identifiers_cannot_escape_service_authenticated_urls(
    gateway, monkeypatch
):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from off_key_api_gateway.api.v1 import anomalies
    from off_key_api_gateway.facades.tactic import Tactic
    from yarl import URL

    monkeypatch.setenv("INTERNAL_API_SECRET", "test-private-api-credential-123456789")
    get_service_auth_settings.cache_clear()
    gateway.dependency_overrides[access.current_member] = lambda: PROFILE
    captured = []

    @asynccontextmanager
    async def request(method, url, **kwargs):
        captured.append((URL(url).raw_path, kwargs["headers"]))
        yield SimpleNamespace(status=200, json=AsyncMock(return_value=[]))

    facade = Tactic()
    monkeypatch.setattr(
        facade, "_get_session", AsyncMock(return_value=SimpleNamespace(request=request))
    )
    monkeypatch.setattr(favorites, "tactic", facade)
    monkeypatch.setattr(anomalies, "tactic", facade)
    async with asgi_client(gateway) as client:
        for identifier in (
            "../../99/favorites/charger-1",
            "../../../anomalies/1",
            "../../../../orchestration/radar/services/victim",
            "%2e%2e/%2e%2e/99/favorites/charger-1",
            "..",
            ".",
        ):
            response = await client.request(
                "DELETE", "/v1/favorites", json={"charger_id": identifier}
            )
            assert response.status_code == 422
        assert (
            await client.get(
                "/v1/anomalies", params={"charger_id": "../users/99/favorites"}
            )
        ).status_code == 422
        assert not captured
        assert (
            await client.request(
                "DELETE", "/v1/favorites", json={"charger_id": "charger-1"}
            )
        ).status_code == 200
        assert captured[-1][0] == "/api/v1/data/users/17/favorites/charger-1"
        assert (
            await client.request(
                "DELETE", "/v1/favorites", json={"charger_id": "%2e%2e%2f99"}
            )
        ).status_code == 200
        assert captured[-1][0] == "/api/v1/data/users/17/favorites/%252e%252e%252f99"
    await facade.request(
        "GET", "/api/v1/members/me", headers={"Authorization": "Bearer user"}
    )
    assert captured[-1][1] == {
        "Authorization": "Bearer user",
        "X-Off-Key-Service-Key": "test-private-api-credential-123456789",
    }


@pytest.fixture
def failing_login(gateway, monkeypatch):
    from slowapi.middleware import SlowAPIMiddleware

    gateway.add_middleware(SlowAPIMiddleware)
    monkeypatch.setattr(
        auth.tactic,
        "authenticate_user",
        AsyncMock(side_effect=TacticError("Invalid credentials", status=401)),
    )
    return gateway


def _login(email=PROFILE.email):
    return {"email": email, "password": "wrong"}


@pytest.mark.asyncio
async def test_direct_clients_cannot_spoof_forwarded_addresses(failing_login):
    async with asgi_client(failing_login, client=("203.0.113.5", 80)) as client:
        for number in range(10):
            response = await client.post(
                "/v1/auth/login",
                json=_login(),
                headers={"X-Forwarded-For": f"198.51.100.{number}"},
            )
            assert response.status_code == 401
        assert (
            await client.post(
                "/v1/auth/login",
                json=_login(),
                headers={"X-Forwarded-For": "203.0.113.9"},
            )
        ).status_code == 429


@pytest.mark.asyncio
async def test_attackers_behind_the_proxy_cannot_lock_out_another_client(
    failing_login,
):
    async with asgi_client(failing_login, client=("10.0.1.7", 80)) as client:
        # A client-supplied left-most entry is ignored; Traefik appends the peer.
        attacker = {"X-Forwarded-For": "198.51.100.1, 203.0.113.66"}
        for _ in range(10):
            response = await client.post(
                "/v1/auth/login", json=_login(), headers=attacker
            )
            assert response.status_code == 401
        assert (
            await client.post("/v1/auth/login", json=_login(), headers=attacker)
        ).status_code == 429
        assert (
            await client.post(
                "/v1/auth/login",
                json=_login(),
                headers={"X-Forwarded-For": "198.51.100.1, 203.0.113.77"},
            )
        ).status_code == 401


@pytest.mark.asyncio
async def test_one_client_cannot_spray_guesses_across_accounts(failing_login):
    async with asgi_client(failing_login, client=("10.0.1.7", 80)) as client:
        sprayer = {"X-Forwarded-For": "203.0.113.66"}
        for number in range(30):
            response = await client.post(
                "/v1/auth/login",
                json=_login(f"member{number}@example.com"),
                headers=sprayer,
            )
            assert response.status_code == 401
        assert (
            await client.post(
                "/v1/auth/login",
                json=_login("another@example.com"),
                headers=sprayer,
            )
        ).status_code == 429
        assert (
            await client.post(
                "/v1/auth/login",
                json=_login("another@example.com"),
                headers={"X-Forwarded-For": "203.0.113.77"},
            )
        ).status_code == 401


@pytest.mark.asyncio
async def test_invalid_invitation_is_validation_error_and_remains_rate_limited(
    gateway, monkeypatch
):
    from off_key_tactic_middleware.api.v1 import members
    from off_key_tactic_middleware.domain import (
        ValidationError as DomainValidationError,
    )

    internal = FastAPI()
    internal.include_router(members.router)
    internal.dependency_overrides[members.member_service] = lambda: type(
        "Service",
        (),
        {
            "accept_invitation": AsyncMock(
                side_effect=DomainValidationError("Invalid or expired invitation")
            )
        },
    )()
    async with asgi_client(internal, base_url="http://tactic") as client:
        response = await client.post(
            "/members/accept-invitation",
            json={"token": "t" * 43, "password": "long-enough-password"},
        )
    assert response.status_code == 422
    monkeypatch.setattr(
        auth.tactic,
        "request",
        AsyncMock(side_effect=TacticError("Invalid or expired invitation", status=422)),
    )
    async with asgi_client(gateway) as client:
        for _ in range(10):
            assert (
                await client.post(
                    "/v1/auth/accept-invitation",
                    json={"token": "t" * 43, "password": "long-enough-password"},
                )
            ).status_code == 422
        assert (
            await client.post(
                "/v1/auth/accept-invitation",
                json={"token": "t" * 43, "password": "long-enough-password"},
            )
        ).status_code == 429
        assert (
            await client.post(
                "/v1/auth/accept-invitation",
                json={"token": "u" * 43, "password": "long-enough-password"},
            )
        ).status_code == 422
