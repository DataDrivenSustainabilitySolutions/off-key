"""Temporary observation contracts, authorization, decoding and resource bounds."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from off_key_api_gateway.api.v1 import system as gateway
from off_key_core.db.base import get_db_async
from off_key_core.db.models import User
from off_key_core.schemas.system import SystemStream
from off_key_core.schemas.system_live import SystemLiveStart
from off_key_core.utils.enum import RoleEnum
from off_key_core.utils.payload_decode import decode_value
from off_key_tactic_middleware.api.collection_auth import current_member
from off_key_tactic_middleware.api.v1 import system as system_api
from off_key_tactic_middleware.api.v1 import system_live as live_api
from off_key_tactic_middleware.config.system_live import (
    LiveCredential,
    LiveSocksProxy,
    SystemLiveSettings,
)
from off_key_tactic_middleware.services.system import SystemService
from off_key_tactic_middleware.services.system_live import (
    LiveSessionError,
    SystemLiveService,
)
from off_key_tactic_middleware.services.system_live_mqtt import LiveMqttWorker
from socks import SOCKS5

from tests.support.system_live import FakeWorker, manager, snapshot


class UnavailableWorker(FakeWorker):
    def start(self):
        self.started = True
        self.state("reconnecting", "Broker unavailable.")


@pytest.mark.asyncio
async def test_private_proxy_routes_only_exact_hosts_and_does_not_bypass_allowlist():
    service, _ = manager(
        SYSTEM_LIVE_SOCKS_PROXIES={"broker": {"host": "tailnet-proxy", "port": 1055}}
    )
    saved = snapshot()
    saved.document.connections.append(
        saved.document.connections[0].model_copy(
            update={"id": "direct", "host": "direct"}
        )
    )
    saved.document.streams.append(
        saved.document.streams[0].model_copy(
            update={"id": "direct-reading", "connection_id": "direct"}
        )
    )
    service.settings.SYSTEM_LIVE_ALLOWED_HOSTS.append("direct")
    data = await service.acquire(saved, 1, 1)
    assert service.workers[0].proxy.host == "tailnet-proxy"
    assert service.workers[1].proxy is None
    assert "tailnet-proxy" not in json.dumps(data)
    await service.stop()
    service.settings.SYSTEM_LIVE_ALLOWED_HOSTS.clear()
    denied = await service.acquire(snapshot(), 1, 1)
    assert denied["telemetry"]["connections"][0]["state"] == "blocked"
    assert not service.workers
    await service.stop()


def test_proxy_uses_remote_dns_and_keeps_original_mqtt_tls_hostname():
    connection = snapshot().document.connections[0]
    connection.tls = True
    client = MagicMock()
    worker = LiveMqttWorker(
        connection,
        ["room/values"],
        None,
        MagicMock(),
        MagicMock(),
        proxy=LiveSocksProxy(
            host="tailnet-proxy", username="reader", password="secret"
        ),
        client_factory=lambda *_args, **_kwargs: client,
    )
    client.proxy_set.assert_called_once_with(
        proxy_type=SOCKS5,
        proxy_addr="tailnet-proxy",
        proxy_port=1055,
        proxy_rdns=True,
        proxy_username="reader",
        proxy_password="secret",
    )
    client.tls_set.assert_called_once_with()
    worker.start()
    client.connect_async.assert_called_once_with("broker", 1883, keepalive=30)
    worker.stop()


def test_private_proxy_config_normalizes_exact_hosts_and_hides_secrets():
    settings = SystemLiveSettings(
        SYSTEM_LIVE_SOCKS_PROXIES='{"BROKER.":{"host":"TAILNET-PROXY.","password":"private-password"}}'
    )
    assert list(settings.SYSTEM_LIVE_SOCKS_PROXIES) == ["broker"]
    assert settings.SYSTEM_LIVE_SOCKS_PROXIES["broker"].host == "tailnet-proxy"
    assert "private-password" not in repr(settings)
    assert "tailnet-proxy" not in json.dumps(settings.limits)
    with pytest.raises(ValueError):
        SystemLiveSettings(
            SYSTEM_LIVE_SOCKS_PROXIES={"*.example.com": {"host": "proxy"}}
        )
    with pytest.raises(ValueError):
        LiveSocksProxy(host="https://proxy.example.com")


@pytest.mark.asyncio
async def test_unreachable_broker_has_one_deadline_and_stops_late_callbacks():
    service, now = manager()
    service.worker_factory = UnavailableWorker
    await service.acquire(snapshot(), 1, 1)
    worker = service.workers[0]
    for second in range(1, 15):
        now[0] = 100 + second
        worker.state("reconnecting", "Retrying.")
        await service.reconcile(snapshot())
        assert not worker.stopped
    now[0] = 115
    await service.reconcile(snapshot())
    assert worker.stopped and not service.workers
    connection = service.snapshot(0)["connections"][0]
    assert connection["state"] == "error"
    assert "15 seconds" in connection["message"]
    worker.state("connected", None)
    worker.message("room/values", b'{"temperature":20}', False)
    assert service.snapshot(0)["connections"][0] == connection
    assert not service.snapshot(0)["samples"]
    await service.stop()


@pytest.mark.asyncio
async def test_timeout_stops_only_failed_broker_and_connected_silence_is_valid():
    service, now = manager()
    saved = snapshot()
    saved.document.connections.append(
        saved.document.connections[0].model_copy(update={"id": "broker-two"})
    )
    saved.document.streams.append(
        saved.document.streams[0].model_copy(
            update={"id": "temperature-two", "connection_id": "broker-two"}
        )
    )
    await service.acquire(saved, 1, 1)
    healthy, failing = service.workers
    failing.state("reconnecting", "Disconnected.")
    now[0] += 15
    await service.reconcile(saved)
    assert failing.stopped and not healthy.stopped
    assert service.workers == [healthy]
    assert [state["state"] for state in service.snapshot(0)["connections"]] == [
        "connected",
        "error",
    ]
    healthy.message("room/values", b'{"temperature":20}', False)
    assert service.snapshot(0)["streams"][0]["value"] == 20
    await service.stop()


@pytest.mark.asyncio
async def test_successful_recovery_resets_budget_for_a_new_outage():
    service, now = manager()
    await service.acquire(snapshot(), 1, 1)
    worker = service.workers[0]
    worker.state("reconnecting", "Disconnected.")
    now[0] += 14
    worker.state("connecting", "Subscribing.")
    worker.state("connected", None)
    now[0] += 10
    await service.reconcile(snapshot())
    assert not worker.stopped
    worker.state("reconnecting", "Disconnected again.")
    now[0] += 14
    await service.reconcile(snapshot())
    assert not worker.stopped
    now[0] += 1
    await service.reconcile(snapshot())
    assert worker.stopped
    await service.stop()


@pytest.mark.asyncio
async def test_denied_connection_stops_without_retry_and_explicit_retry_starts_fresh():
    service, _ = manager()
    first = await service.acquire(snapshot(), 1, 1)
    worker = service.workers[0]
    worker.state("error", "The broker rejected the connection credentials.")
    worker.state("reconnecting", "Must not revive a denial.")
    await service.reconcile(snapshot())
    assert worker.stopped and not service.workers
    assert service.snapshot(0)["connections"][0]["state"] == "error"
    second = await service.acquire(snapshot(), 2, 1)
    assert len(service.workers) == 1 and service.workers[0] is not worker
    assert second["telemetry"]["connections"][0]["state"] == "connected"
    assert len(service.leases) == 2
    await service.release(1, first["lease_id"])
    assert not service.workers[0].stopped
    await service.release(2, second["lease_id"])


@pytest.mark.parametrize(
    "kind,pointer,payload,expected",
    [
        ("number", None, b"12.5", 12.5),
        ("boolean", None, b"true", True),
        ("text", None, b"working", "working"),
        ("identifier", None, b"00023", "00023"),
        ("text", None, b'"123"', "123"),
        ("number", "/a~1b/c~0d/0", b'{"a/b":{"c~d":[7]}}', 7),
        ("number", "", b"-4", -4),
        ("boolean", "/values/active", b'{"values":{"active":false}}', False),
        ("identifier", "/id", b'{"id":"0012"}', "0012"),
    ],
)
def test_typed_values_and_json_pointer(kind, pointer, payload, expected):
    stream = SystemStream(
        id="reading",
        label="Reading",
        connection_id="broker",
        topic="values",
        value_type=kind,
        payload_pointer=pointer,
    )
    assert decode_value(payload, stream) == expected


@pytest.mark.parametrize(
    "kind,pointer,payload",
    [
        ("number", None, b"true"),
        ("boolean", None, b"1"),
        ("number", None, b"NaN"),
        ("number", None, b"1e10000"),
        ("text", None, b"\xff"),
        ("text", None, b"x" * 513),
        ("text", None, b'"bad\\u0000text"'),
        ("number", "/missing", b'{"reading":1}'),
        ("number", "/01", b"[1,2]"),
        ("number", "/-", b"[1,2]"),
        ("number", None, b"1" * 65537),
        ("number", None, b"[1,2]"),
    ],
)
def test_invalid_and_oversized_values_are_rejected(kind, pointer, payload):
    stream = SystemStream(
        id="reading",
        label="Reading",
        connection_id="broker",
        topic="values",
        value_type=kind,
        payload_pointer=pointer,
    )
    with pytest.raises((ValueError, UnicodeError)):
        decode_value(payload, stream)


def test_settings_default_closed_and_empty_private_credentials(monkeypatch):
    monkeypatch.setenv("SYSTEM_LIVE_CREDENTIALS", "")
    settings = SystemLiveSettings(_env_file=None)
    assert not settings.SYSTEM_LIVE_ENABLED
    assert not settings.allows_host("broker")
    assert settings.SYSTEM_LIVE_CREDENTIALS == {}


@pytest.mark.asyncio
async def test_start_is_explicit_shared_by_leases_and_owner_bound():
    service, _ = manager()
    assert service.snapshot(0)["mode"] == "configured_only"
    assert service.workers == []
    first = await service.acquire(snapshot(), owner=10, revision=1)
    worker = service.workers[0]
    assert worker.started and worker.topics == ["room/values"]
    second = await service.acquire(snapshot(), owner=11, revision=1)
    assert service.workers == [worker]
    with pytest.raises(LiveSessionError) as failure:
        await service.release(owner=11, lease=first["lease_id"])
    assert failure.value.status == 404
    await service.release(10, first["lease_id"])
    assert not worker.stopped
    await service.release(11, second["lease_id"])
    assert worker.stopped
    assert service.snapshot(0)["streams"] == []
    assert service.snapshot(0)["samples"] == []
    assert service.snapshot(0)["mode"] == "configured_only"


@pytest.mark.asyncio
async def test_observation_counts_retention_errors_and_coalescing_exactly():
    service, now = manager()
    await service.acquire(snapshot(), 1, 1)
    worker = service.workers[0]
    worker.message("unsubscribed", b"999", False)
    worker.message("room/values", b'{"temperature":20}', True)
    for _ in range(10000):
        worker.message("room/values", b'{"temperature":21}', False)
    worker.message("room/values", b'{"temperature":"invalid"}', False)
    data = service.snapshot(0)
    connection, stream = data["connections"][0], data["streams"][0]
    assert connection["received_messages"] == 10002
    assert connection["fresh_count"] == 10001
    assert connection["retained_count"] == 1
    assert stream["received_count"] == 10002
    assert stream["fresh_count"] == 10001
    assert stream["retained_count"] == 1
    assert stream["decode_errors"] == 1
    assert stream["value"] == 21
    assert stream["rate_hz"] == 2000.2
    assert len(data["samples"]) == 1
    cursor = data["sequence"]
    now[0] += 6
    decayed = service.snapshot(cursor)
    assert decayed["streams"][0]["rate_hz"] == 0
    assert decayed["connections"][0]["rate_hz"] == 0
    assert not decayed["samples"]


@pytest.mark.asyncio
async def test_retained_snapshot_does_not_create_fresh_rate_or_fresh_last_seen():
    service, _ = manager()
    await service.acquire(snapshot(), 1, 1)
    service.workers[0].message("room/values", b'{"temperature":20}', True)
    data = service.snapshot(0)
    assert data["streams"][0]["fresh_received_at"] is None
    assert data["streams"][0]["rate_hz"] == 0
    assert data["connections"][0]["rate_hz"] == 0
    assert data["samples"][0]["is_retained"] is True


@pytest.mark.asyncio
async def test_malformed_fresh_arrivals_drive_activity_without_overwriting_values():
    service, now = manager()
    await service.acquire(snapshot(), 1, 1)
    worker = service.workers[0]
    worker.message("room/values", b'{"temperature":20}', True)
    before = service.snapshot(0)
    now[0] += 1
    worker.message("room/values", b"malformed", False)
    data = service.snapshot(before["sequence"])
    stream = data["streams"][0]
    assert stream["fresh_count"] == 1
    assert stream["retained_count"] == 1
    assert stream["rate_hz"] == 0.2
    assert stream["fresh_received_at"] is not None
    assert stream["value"] == 20
    assert stream["received_at"] == before["streams"][0]["received_at"]
    assert stream["is_retained"] is True
    assert stream["decode_errors"] == 1
    assert data["samples"] == []


@pytest.mark.asyncio
async def test_history_is_bounded_and_stale_cursors_reset():
    service, now = manager(SYSTEM_LIVE_MAX_SAMPLES=64)
    await service.acquire(snapshot(), 1, 1)
    for number in range(200):
        service.workers[0].message(
            "room/values", json.dumps({"temperature": number}).encode(), False
        )
        now[0] += 1
    data = service.snapshot(1)
    assert len(data["samples"]) == 64
    assert data["reset"] is True
    assert data["streams"][0]["received_count"] == 200
    assert service.snapshot(data["sequence"])["samples"] == []
    assert service.snapshot(data["sequence"] + 1)["reset"] is True
    now[0] += 7201
    assert service.snapshot(0)["samples"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revision", "document", "expiry"])
async def test_revision_document_or_abandoned_lease_stops_and_wipes(change):
    service, now = manager()
    lease = await service.acquire(snapshot(), 1, 1)
    worker = service.workers[0]
    worker.message("room/values", b'{"temperature":20}', False)
    changed = snapshot()
    if change == "revision":
        changed.revision += 1
    elif change == "document":
        changed.document.streams[0].topic = "new/topic"
    else:
        now[0] += 46
    await service.reconcile(changed)
    assert worker.stopped
    worker.message("room/values", b'{"temperature":99}', False)
    assert service.snapshot(0)["samples"] == []
    assert service.snapshot(0)["mode"] == "configured_only"
    with pytest.raises(LiveSessionError) as failure:
        await service.renew(changed, 1, lease["lease_id"])
    assert failure.value.status == 404


@pytest.mark.asyncio
async def test_private_credentials_and_exact_allowlist_failures_are_publicly_safe():
    service, _ = manager(
        SYSTEM_LIVE_CREDENTIALS={
            "private": {"username": "account", "password": "very-private-password"}
        }
    )
    lease = await service.acquire(snapshot(credential_ref="private"), 1, 1)
    assert (
        service.workers[0].credential.password.get_secret_value()
        == "very-private-password"
    )
    assert "very-private-password" not in json.dumps(lease)
    await service.stop()
    denied = await service.acquire(snapshot(host="unapproved"), 1, 1)
    assert denied["telemetry"]["connections"][0]["state"] == "blocked"
    assert service.workers == []
    await service.stop()
    missing = await service.acquire(snapshot(credential_ref="absent"), 1, 1)
    assert missing["telemetry"]["connections"][0]["state"] == "blocked"
    assert service.workers == []


@pytest.mark.asyncio
async def test_disabled_start_and_stale_revision_never_create_workers():
    service = SystemLiveService(SystemLiveSettings(), worker_factory=FakeWorker)
    with pytest.raises(LiveSessionError) as failure:
        await service.acquire(snapshot(), 1, 1)
    assert failure.value.status == 503
    assert not service.workers
    service, _ = manager()
    with pytest.raises(LiveSessionError) as failure:
        await service.acquire(snapshot(), 1, 0)
    assert failure.value.status == 409
    assert not service.workers


@pytest.mark.asyncio
async def test_concurrent_connection_and_duplicate_topic_fanout_limits():
    service, _ = manager(SYSTEM_LIVE_MAX_CONNECTIONS=1)
    saved = snapshot()
    saved.document.connections.append(
        saved.document.connections[0].model_copy(update={"id": "broker-two"})
    )
    saved.document.streams.append(
        saved.document.streams[0].model_copy(
            update={"id": "temperature-two", "connection_id": "broker-two"}
        )
    )
    data = await service.acquire(saved, 1, 1)
    assert len(service.workers) == 1
    assert data["telemetry"]["connections"][1]["state"] == "blocked"
    await service.stop()
    saved = snapshot()
    saved.document.streams = [
        saved.document.streams[0].model_copy(update={"id": f"reading-{number}"})
        for number in range(65)
    ]
    data = await service.acquire(saved, 1, 1)
    assert data["telemetry"]["connections"][0]["state"] == "blocked"
    assert not service.workers


@pytest.mark.asyncio
async def test_unused_and_blocked_definitions_do_not_consume_live_broker_slots():
    service, _ = manager(SYSTEM_LIVE_MAX_CONNECTIONS=1)
    saved = snapshot()
    active = saved.document.connections[0]
    saved.document.connections = [
        active.model_copy(update={"id": f"unused-{number}"}) for number in range(40)
    ] + [active.model_copy(update={"id": "blocked", "host": "unapproved"}), active]
    saved.document.streams.append(
        saved.document.streams[0].model_copy(
            update={"id": "blocked-reading", "connection_id": "blocked"}
        )
    )
    data = await service.acquire(saved, 1, 1)
    assert len(service.workers) == 1
    assert service.workers[0].connection.id == "broker"
    assert data["telemetry"]["connections"][-1]["state"] == "connected"


@pytest.mark.asyncio
async def test_lease_limit_and_owner_renewal_keep_resources_bounded():
    service, now = manager()
    leases = [await service.acquire(snapshot(), 1, 1) for _ in range(64)]
    assert len(service.workers) == 1
    with pytest.raises(LiveSessionError) as failure:
        await service.acquire(snapshot(), 1, 1)
    assert failure.value.status == 429
    with pytest.raises(LiveSessionError) as failure:
        await service.renew(snapshot(), 2, leases[0]["lease_id"])
    assert failure.value.status == 404
    now[0] += 30
    await service.renew(snapshot(), 1, leases[0]["lease_id"])
    now[0] += 20
    await service.reconcile(snapshot())
    assert len(service.leases) == 1
    assert len(service.workers) == 1
    await service.close()


@pytest.mark.asyncio
async def test_renewal_does_not_resend_retained_sample_history():
    service, _ = manager()
    first = await service.acquire(snapshot(), 1, 1)
    service.workers[0].message("room/values", b'{"temperature":20}', False)
    assert service.snapshot(0)["samples"]
    renewed = await service.renew(snapshot(), 1, first["lease_id"])
    assert renewed["telemetry"]["samples"] == []
    assert renewed["telemetry"]["reset"] is False


@pytest.mark.asyncio
async def test_close_cancels_supervisor_and_disconnects_workers():
    service, _ = manager()
    await service.acquire(snapshot(), 1, 1)
    worker = service.workers[0]
    service.start_supervisor(AsyncMock(return_value=snapshot()))
    task = service.supervisor
    await asyncio.sleep(0)
    await service.close()
    assert task.done() and task.cancelled()
    assert worker.stopped and service.supervisor is None


def test_mqtt_tls_websocket_reconnect_and_suback_state():
    connection = snapshot(credential_ref="private").document.connections[0]
    connection.transport = "websocket"
    connection.websocket_path = "/mqtt"
    connection.tls = True
    client = MagicMock()
    client.subscribe.side_effect = [(0, 1), (0, 2), (0, 3), (0, 4)]
    state = MagicMock()
    worker = LiveMqttWorker(
        connection,
        [f"values/{number}" for number in range(100)],
        LiveCredential(username="account", password="private"),
        MagicMock(),
        state,
        client_factory=lambda *_args, **_kwargs: client,
    )
    client.tls_set.assert_called_once_with()
    client.ws_set_options.assert_called_once_with(path="/mqtt")
    client.username_pw_set.assert_called_once_with("account", "private")
    client.reconnect_delay_set.assert_called_once_with(min_delay=1, max_delay=30)
    worker.start()
    client.connect_async.assert_called_once_with("broker", 1883, keepalive=30)
    good = SimpleNamespace(is_failure=False)
    worker._connected(client, None, None, good, None)
    assert worker.pending == {1, 2}
    worker._subscribed(client, None, 1, [good], None)
    assert state.call_args.args[0] == "connecting"
    worker._subscribed(client, None, 2, [good], None)
    assert state.call_args.args == ("connected", None)
    worker._disconnected(client, None, None, good, None)
    assert state.call_args.args[0] == "reconnecting"
    worker._connected(client, None, None, good, None)
    assert client.subscribe.call_count == 4
    worker._subscribed(client, None, 3, [SimpleNamespace(is_failure=True)], None)
    assert state.call_args.args[0] == "error"
    worker.stop()
    client.loop_stop.assert_called_once()


def _api(monkeypatch, *, role=RoleEnum.user, authenticated=True):
    app = FastAPI()
    app.include_router(system_api.router)
    service, _ = manager()
    app.state.system_live = service
    if authenticated:
        app.dependency_overrides[current_member] = lambda: User(
            id=1, email="member@example.com", role=role
        )
    app.dependency_overrides[get_db_async] = lambda: AsyncMock()
    monkeypatch.setattr(SystemService, "read", AsyncMock(return_value=snapshot()))
    monkeypatch.setattr(live_api, "require_application_writes", AsyncMock())
    return app, service


def test_live_route_requires_sign_in_and_admin_for_broker_actions(monkeypatch):
    app, service = _api(monkeypatch, authenticated=False)
    with TestClient(app) as client:
        assert client.get("/system/live").status_code == 401
        assert (
            client.post(
                "/system/live/leases", json={"expected_revision": 1}
            ).status_code
            == 401
        )
    app, service = _api(monkeypatch)
    with TestClient(app) as client:
        assert client.get("/system/live").status_code == 200
        assert (
            client.post(
                "/system/live/leases", json={"expected_revision": 1}
            ).status_code
            == 403
        )
        assert client.put("/system/live/leases/" + "a" * 32).status_code == 403
        assert client.delete("/system/live/leases/" + "a" * 32).status_code == 403
    assert service.workers == []


def test_admin_route_starts_renews_and_releases_with_no_database_telemetry_writes(
    monkeypatch,
):
    app, service = _api(monkeypatch, role=RoleEnum.admin)
    session = AsyncMock()
    app.dependency_overrides[get_db_async] = lambda: session
    with TestClient(app) as client:
        result = client.post("/system/live/leases", json={"expected_revision": 1})
        assert result.status_code == 200
        lease_id = result.json()["lease_id"]
        assert client.put("/system/live/leases/" + lease_id).status_code == 200
        service.workers[0].message("room/values", b'{"temperature":20}', False)
        assert client.get("/system/live").json()["samples"][0]["value"] == 20
        assert client.delete("/system/live/leases/" + lease_id).status_code == 204
        assert client.get("/system/live").json()["mode"] == "configured_only"
    session.add.assert_not_called()
    session.execute.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_gateway_preserves_authorization_and_live_request_contract(monkeypatch):
    request = AsyncMock(return_value={"mode": "configured_only"})
    monkeypatch.setattr(gateway.tactic, "request", request)
    await gateway.start_live(SystemLiveStart(expected_revision=7), "Bearer token")
    request.assert_awaited_with(
        "POST",
        "/api/v1/system/live/leases",
        json_data={"expected_revision": 7},
        headers={"Authorization": "Bearer token"},
    )
    await gateway.get_live(12, "Bearer token")
    request.assert_awaited_with(
        "GET",
        "/api/v1/system/live?after_sequence=12",
        json_data=None,
        headers={"Authorization": "Bearer token"},
    )
    lease_id = "b" * 32
    await gateway.renew_live(lease_id, "Bearer token")
    assert request.await_args.args == ("PUT", f"/api/v1/system/live/leases/{lease_id}")
    await gateway.stop_live(lease_id, "Bearer token")
    assert request.await_args.args == (
        "DELETE",
        f"/api/v1/system/live/leases/{lease_id}",
    )
