"""HTTP regressions for the API's trust boundaries between callers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from off_key_api_gateway import providers
from off_key_api_gateway.api import access
from off_key_api_gateway.api.rate_limiter import limiter
from off_key_api_gateway.api.v1 import auth
from off_key_core.auth.permissions import Permission
from off_key_core.schemas.favorites import FavoriteRef
from off_key_core.schemas.members import AcceptInvitation
from off_key_tactic_middleware.domain import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
)
from off_key_tactic_middleware.domain import (
    ValidationError as DomainValidationError,
)
from off_key_tactic_middleware.main import create_app
from pydantic import ValidationError

from tests.support.env import set_auth_env
from tests.support.gateway import Callers, gateway_app, member, returning
from tests.support.http import asgi_client

PROFILE = member(email="member@example.com")
ADMIN = member("admin", email="admin@example.com")


@pytest.fixture
def services():
    return SimpleNamespace(
        users=AsyncMock(),
        members=AsyncMock(),
        favorites=AsyncMock(),
        monitors=AsyncMock(),
        alarms=AsyncMock(),
        data=AsyncMock(),
    )


@pytest.fixture
def gateway(services, monkeypatch):
    set_auth_env(monkeypatch)
    app = gateway_app(
        overrides={
            providers.get_user_service: returning(services.users),
            providers.get_member_service: returning(services.members),
            providers.get_favorite_service: returning(services.favorites),
            providers.get_radar_orchestration_service: returning(services.monitors),
            providers.get_alarm_service: returning(services.alarms),
            providers.get_catalogue_data_service: returning(services.data),
        }
    )
    yield app
    limiter.reset()


def signed_in(gateway, caller):
    gateway.dependency_overrides[access.current_caller] = lambda: caller


def asked(services) -> list:
    return [call for service in vars(services).values() for call in service.mock_calls]


@pytest.mark.asyncio
async def test_anonymous_and_invalid_tokens_cannot_reach_business_handlers(
    gateway, services, monkeypatch
):
    Callers(monkeypatch)
    paths = (
        "/devices",
        "/readings/example/measurements",
        "/monitors",
        "/favorites?user_id=99",
        "/alarms/count",
        "/catalogue",
        "/members",
    )
    async with asgi_client(gateway) as client:
        for path in paths:
            assert (await client.get("/v1" + path)).status_code == 401
            assert (
                await client.get(
                    "/v1" + path, headers={"Authorization": "Bearer invalid"}
                )
            ).status_code == 401
    assert asked(services) == []


@pytest.mark.asyncio
async def test_members_can_read_and_favorite_only_for_themselves(gateway, services):
    signed_in(gateway, PROFILE)
    device = {"kind": "device", "id": "charger-1"}
    stored = device | {"created_at": "2026-11-05T00:00:00Z"}
    services.favorites.list_favorites.return_value = [stored]
    services.favorites.add_favorite.return_value = stored
    get, add = services.favorites.list_favorites, services.favorites.add_favorite
    async with asgi_client(gateway) as client:
        response = await client.get("/v1/favorites?user_id=99")
        assert response.json() == [stored]
        get.assert_awaited_once_with(user_id=17, kind=None)
        assert (
            await client.post("/v1/favorites", json=device | {"user_id": 99})
        ).status_code == 422
        add.assert_not_awaited()
        assert (await client.post("/v1/favorites", json=device)).status_code == 200
        add.assert_awaited_once_with(user_id=17, ref=FavoriteRef(**device))
        services.favorites.reset_mock()
        for method, path in (
            ("DELETE", "/members/19"),
            ("POST", "/monitors"),
            ("POST", "/monitors/example/stop"),
            ("DELETE", "/monitors/example"),
            ("POST", "/pipelines/apply"),
            ("POST", "/pipeline-activations/example/cancel"),
            ("POST", "/pipeline-blocks"),
            ("DELETE", "/pipeline-blocks/example"),
            ("POST", "/alarms"),
            ("DELETE", "/alarms/example"),
            ("GET", "/members"),
            ("POST", "/invitations"),
            ("PATCH", "/members/19"),
            ("POST", "/roles"),
            ("PATCH", "/roles/operator"),
            ("DELETE", "/roles/operator"),
        ):
            assert (
                await client.request(method, "/v1" + path, json={})
            ).status_code == 403, (method, path)
    assert asked(services) == []


@pytest.mark.asyncio
async def test_admin_can_manage_monitors(gateway, services):
    signed_in(gateway, ADMIN)
    services.monitors.delete_radar_service.return_value = True
    async with asgi_client(gateway) as client:
        response = await client.delete("/v1/monitors/example")
    assert response.status_code == 204
    services.monitors.delete_radar_service.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_custom_role_changes_only_what_its_permissions_cover(gateway, services):
    signed_in(
        gateway,
        member(
            "alarm-desk",
            permissions=[Permission.manage_alarms],
            email="member@example.com",
        ),
    )
    async with asgi_client(gateway) as client:
        alarm = await client.delete("/v1/alarms/example")
        monitor = await client.delete("/v1/monitors/example")
        members = await client.get("/v1/members")
        reads = await client.get("/v1/permissions")
    assert alarm.status_code == 204, alarm.text
    services.alarms.delete_alarm.assert_awaited_once()
    assert monitor.status_code == 403
    assert "manage_monitors" in monitor.json()["detail"]
    services.monitors.delete_radar_service.assert_not_awaited()
    assert members.status_code == 403
    assert reads.status_code == 200
    assert [entry["id"] for entry in reads.json()] == [p.value for p in Permission]


@pytest.mark.asyncio
async def test_role_changes_carry_only_the_fields_sent(gateway, services):
    signed_in(gateway, ADMIN)
    role = {
        "id": "operator",
        "name": "Operator",
        "permissions": ["manage_monitors"],
        "editable": True,
        "built_in": False,
        "members": 0,
    }
    services.members.update_role.return_value = role
    async with asgi_client(gateway) as client:
        response = await client.patch(
            "/v1/roles/operator", json={"permissions": ["manage_monitors"]}
        )
        unknown = await client.post(
            "/v1/roles", json={"name": "Desk", "permissions": ["launch_rockets"]}
        )
    assert response.status_code == 200, response.text
    assert response.json() == role
    role_id, change, actor = services.members.update_role.await_args.args
    assert (role_id, actor) == ("operator", ADMIN)
    assert change.model_dump(exclude_unset=True) == {"permissions": ["manage_monitors"]}
    assert unknown.status_code == 422


@pytest.mark.asyncio
async def test_the_worker_serves_probes_only_and_grants_no_cross_origin_access():
    """Browsers reach the API alone; the worker answers its probes and nothing
    else."""
    async with asgi_client(create_app()) as client:
        response = await client.get(
            "/health", headers={"Origin": "https://evil.example"}
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers
        for method, path in (
            ("DELETE", "/api/v1/members/19"),
            ("GET", "/api/v1/data/devices"),
            ("POST", "/api/v1/data/alarms/query"),
            ("GET", "/api/v1/system"),
            ("GET", "/api/v1/members/me"),
            ("GET", "/openapi.json"),
            ("GET", "/docs"),
        ):
            assert (await client.request(method, path, json={})).status_code in (
                404,
                405,
            ), path


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status, failure",
    [
        (204, None),
        (404, NotFoundError("No such member")),
        (409, ConflictError("Cannot remove the last admin")),
    ],
)
async def test_admin_member_removal_names_the_actor_and_keeps_the_status(
    gateway, services, status, failure
):
    signed_in(gateway, ADMIN)
    services.members.remove.side_effect = failure
    async with asgi_client(gateway) as client:
        response = await client.delete("/v1/members/19")
    assert response.status_code == status
    if status == 204:
        assert response.content == b""
    services.members.remove.assert_awaited_once_with(19, ADMIN)


@pytest.mark.asyncio
async def test_anonymous_member_removal_reaches_nothing(gateway, services):
    async with asgi_client(gateway) as client:
        assert (await client.delete("/v1/members/19")).status_code == 401
    assert asked(services) == []


@pytest.mark.asyncio
async def test_password_reset_does_not_disclose_membership_and_login_is_limited(
    gateway, services, monkeypatch
):
    services.members.issue_reset_token.side_effect = [
        None,
        {"email": PROFILE.email, "token": "x" * 43},
    ]
    monkeypatch.setattr(auth, "send_password_reset_email", AsyncMock())
    services.users.authenticate.side_effect = AuthenticationError("Invalid credentials")
    async with asgi_client(gateway) as client:
        missing = await client.post(
            "/v1/auth/password-reset", json={"email": "missing@example.com"}
        )
        present = await client.post(
            "/v1/auth/password-reset", json={"email": PROFILE.email}
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
async def test_path_identifiers_cannot_escape_their_member(gateway, services):
    signed_in(gateway, PROFILE)
    async with asgi_client(gateway) as client:
        # Favorite ids travel as query values and the member comes from the
        # token, so no id can name another member's favorites.
        for identifier in (
            "../../99/favorites/charger-1",
            "%2e%2e/%2e%2e/99/favorites/charger-1",
            "..",
        ):
            response = await client.request(
                "DELETE", "/v1/favorites", params={"kind": "device", "id": identifier}
            )
            assert response.status_code == 204
            assert services.favorites.remove_favorite.await_args.kwargs == {
                "user_id": 17,
                "ref": FavoriteRef(kind="device", id=identifier),
            }


@pytest.fixture
def failing_login(gateway, services):
    from slowapi.middleware import SlowAPIMiddleware

    gateway.add_middleware(SlowAPIMiddleware)
    services.users.authenticate.side_effect = AuthenticationError("Invalid credentials")
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
    gateway, services
):
    services.members.accept_invitation.side_effect = DomainValidationError(
        "Invalid or expired invitation"
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
