"""HTTP regressions for the public gateway and private TACTIC trust boundaries."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from off_key_api_gateway.api import access
from off_key_api_gateway.api.rate_limiter import limiter, rate_limit_exceeded_handler
from off_key_api_gateway.api.v1 import auth, favorites, monitors
from off_key_api_gateway.api.v1.routes import router
from off_key_api_gateway.facades.tactic import TacticError
from off_key_core.config.service_auth import get_service_auth_settings
from off_key_core.schemas.members import AcceptInvitation, MemberProfile
from off_key_tactic_middleware.main import create_app
from pydantic import ValidationError

PROFILE = MemberProfile(
    id=17,
    email="member@example.com",
    role="user",
    is_active=True,
    is_verified=True,
    created_at=datetime.now(UTC),
)


@pytest.fixture
def gateway():
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.state.limiter = limiter
    app.add_exception_handler(429, rate_limit_exceeded_handler)
    limiter.reset()
    yield app
    limiter.reset()


@pytest.mark.asyncio
async def test_anonymous_and_invalid_tokens_cannot_reach_business_handlers(
    gateway, monkeypatch
):
    remote = AsyncMock(side_effect=TacticError("Invalid token", status=401))
    monkeypatch.setattr(access.tactic, "_make_request", remote)
    paths = (
        "/chargers/available",
        "/telemetry/example/type",
        "/monitors/all",
        "/favorites?user_id=99",
        "/anomalies/count",
        "/sources",
        "/members",
    )
    async with AsyncClient(
        transport=ASGITransport(app=gateway), base_url="http://test"
    ) as client:
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
    async with AsyncClient(
        transport=ASGITransport(app=gateway), base_url="http://test"
    ) as client:
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
    async with AsyncClient(
        transport=ASGITransport(app=gateway), base_url="http://test"
    ) as client:
        response = await client.delete("/v1/monitors/example")
    assert response.status_code == 200
    delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_tactic_rejects_direct_business_requests_without_service_credential(
    monkeypatch,
):
    monkeypatch.setenv("INTERNAL_API_SECRET", "test-private-api-credential-123456789")
    get_service_auth_settings.cache_clear()
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/health")).status_code == 200
        for method, path in (
            ("GET", "/api/v1/data/chargers"),
            ("POST", "/api/v1/data/users"),
            ("POST", "/api/v1/data/auth/login"),
            ("GET", "/api/v1/collection"),
            ("GET", "/api/v1/members/me"),
        ):
            assert (await client.request(method, path, json={})).status_code == 401
            assert (
                await client.request(
                    method, path, headers={"X-Off-Key-Service-Key": "wrong"}, json={}
                )
            ).status_code == 401
    get_service_auth_settings.cache_clear()


@pytest.mark.asyncio
async def test_password_reset_does_not_disclose_membership_and_login_is_limited(
    gateway, monkeypatch
):
    reset = AsyncMock(side_effect=[None, {"email": PROFILE.email, "token": "x" * 43}])
    monkeypatch.setattr(auth.tactic, "_make_request", reset)
    monkeypatch.setattr(auth, "send_password_reset_email", AsyncMock())
    authenticate = AsyncMock(side_effect=TacticError("Invalid credentials", status=401))
    monkeypatch.setattr(auth.tactic, "authenticate_user", authenticate)
    async with AsyncClient(
        transport=ASGITransport(app=gateway), base_url="http://test"
    ) as client:
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
    async with AsyncClient(
        transport=ASGITransport(app=gateway), base_url="http://test"
    ) as client:
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
    await facade._make_request(
        "GET", "/api/v1/members/me", headers={"Authorization": "Bearer user"}
    )
    assert captured[-1][1] == {
        "Authorization": "Bearer user",
        "X-Off-Key-Service-Key": "test-private-api-credential-123456789",
    }
    get_service_auth_settings.cache_clear()


@pytest.mark.asyncio
async def test_auth_limits_are_independent_behind_proxy_and_ignore_forwarded_spoofing(
    gateway, monkeypatch
):
    from slowapi.middleware import SlowAPIMiddleware

    gateway.add_middleware(SlowAPIMiddleware)
    monkeypatch.setattr(
        auth.tactic,
        "authenticate_user",
        AsyncMock(side_effect=TacticError("Invalid credentials", status=401)),
    )
    async with AsyncClient(
        transport=ASGITransport(app=gateway, client=("10.0.1.7", 80)),
        base_url="http://test",
    ) as client:
        for number in range(10):
            response = await client.post(
                "/v1/auth/login",
                json={"email": PROFILE.email, "password": "wrong"},
                headers={"X-Forwarded-For": f"198.51.100.{number}"},
            )
            assert response.status_code == 401
        assert (
            await client.post(
                "/v1/auth/login",
                json={"email": PROFILE.email, "password": "wrong"},
                headers={"X-Forwarded-For": "203.0.113.9"},
            )
        ).status_code == 429
        assert (
            await client.post(
                "/v1/auth/login",
                json={"email": "colleague@example.com", "password": "wrong"},
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
    async with AsyncClient(
        transport=ASGITransport(app=internal), base_url="http://tactic"
    ) as client:
        response = await client.post(
            "/members/accept-invitation",
            json={"token": "t" * 43, "password": "long-enough-password"},
        )
    assert response.status_code == 422
    monkeypatch.setattr(
        auth.tactic,
        "_make_request",
        AsyncMock(side_effect=TacticError("Invalid or expired invitation", status=422)),
    )
    async with AsyncClient(
        transport=ASGITransport(app=gateway), base_url="http://test"
    ) as client:
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
