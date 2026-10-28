"""On-demand broker connection checks: one CONNECT, classified, never subscribed."""

import asyncio
import socket
import ssl
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from off_key_api_gateway.api.v1 import system as gateway
from off_key_core.db.base import get_db_async
from off_key_core.db.models import User
from off_key_core.schemas.system import SystemConnection, SystemConnectionCheckScope
from off_key_core.utils.enum import RoleEnum
from off_key_tactic_middleware.api.collection_auth import current_member
from off_key_tactic_middleware.api.v1 import system as system_api
from off_key_tactic_middleware.config.system_live import (
    LiveCredential,
    SystemLiveSettings,
)
from off_key_tactic_middleware.services.catalogue.broker_check import BrokerCheck
from off_key_tactic_middleware.services.catalogue.system import SystemService
from paho.mqtt.client import WebsocketConnectionError
from socks import ProxyError

from tests.support.mqtt import mqtt_broker, wait_until, withholding_server
from tests.support.system_live import snapshot

pytestmark = pytest.mark.timeout(15)


def _checker(**overrides):
    settings = SystemLiveSettings(
        SYSTEM_LIVE_ALLOWED_HOSTS=["127.0.0.1", "broker"],
        SYSTEM_CONNECTION_CHECK_TIMEOUT_SECONDS=1,
        **overrides,
    )
    return BrokerCheck(settings)


def _connection(port=1883, **fields):
    return SystemConnection(
        id="broker", label="Broker", host="127.0.0.1", port=port, **fields
    )


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


async def test_a_live_broker_is_reachable_and_nothing_is_subscribed():
    async with mqtt_broker() as (broker, port):
        result = await _checker().check(_connection(port))
        assert result.status == "reachable"
        assert result.message is None
        assert result.latency_ms is not None
        assert broker._subscriptions == {}


async def test_refused_credentials_are_reported_as_rejected():
    async with withholding_server("refuse") as peer:
        result = await _checker(
            SYSTEM_LIVE_CREDENTIALS={"named": LiveCredential(username="old")}
        ).check(_connection(peer.port, credential_ref="named"))
    assert result.status == "auth_rejected"
    assert peer.connections == 1


async def test_a_silent_peer_times_out_and_its_socket_is_closed():
    async with withholding_server("connack") as peer:
        result = await _checker().check(_connection(peer.port))
        assert result.status == "timeout"
        assert peer.connections == 1
        await wait_until(lambda: not peer.writers, 5)


async def test_a_closed_port_is_unreachable():
    result = await _checker().check(_connection(_closed_port()))
    assert result.status == "unreachable"


async def test_tls_against_a_plain_listener_is_a_tls_error():
    async def plain(reader, writer):
        await reader.read(1)
        writer.write(b"not a TLS server\r\n")
        writer.close()

    server = await asyncio.start_server(plain, "127.0.0.1", 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        result = await _checker().check(_connection(port, tls=True))
    assert result.status == "tls_error"


async def test_a_silent_tls_handshake_times_out_with_a_tls_hint():
    async with mqtt_broker() as (_broker, port):
        result = await _checker().check(_connection(port, tls=True))
    assert result.status == "timeout"
    assert "TLS" in result.message


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ssl.SSLCertVerificationError("hostname mismatch"), "tls_error"),
        (socket.gaierror("no such host"), "unreachable"),
        (TimeoutError("timed out"), "timeout"),
        (WebsocketConnectionError("bad upgrade"), "refused"),
        (ProxyError("proxy down"), "unreachable"),
        (OSError("no route"), "unreachable"),
    ],
)
async def test_connect_failures_are_classified_without_their_text(error, status):
    client = MagicMock()
    client.connect.side_effect = error
    client.socket.return_value = None
    checker = _checker()
    checker.client_factory = lambda *_args, **_kwargs: client
    result = await checker.check(_connection())
    assert result.status == status
    assert str(error) not in (result.message or "")
    client.subscribe.assert_not_called()


async def test_blocked_definitions_never_open_a_socket():
    factory = MagicMock()
    checker = _checker()
    checker.client_factory = factory
    outside = SystemConnection(id="old", label="Old", host="elsewhere")
    assert (await checker.check(outside)).status == "blocked"
    missing = _connection(credential_ref="absent")
    assert (await checker.check(missing)).status == "blocked"
    factory.assert_not_called()


def _api(monkeypatch, *, role=RoleEnum.user):
    app = FastAPI()
    app.include_router(system_api.router)
    checker = BrokerCheck(SystemLiveSettings(SYSTEM_LIVE_ALLOWED_HOSTS=["broker"]))
    checker.check = AsyncMock(wraps=checker.check)
    app.state.broker_check = checker
    app.dependency_overrides[current_member] = lambda: User(
        id=1, email="member@example.com", role=role
    )
    app.dependency_overrides[get_db_async] = lambda: AsyncMock()
    monkeypatch.setattr(
        SystemService,
        "read",
        AsyncMock(return_value=snapshot(credential_ref="absent")),
    )
    return app, checker


def test_only_administrators_check_saved_brokers(monkeypatch):
    app, checker = _api(monkeypatch)
    with TestClient(app) as client:
        response = client.post(
            "/system/connections/check", json={"connection_id": "broker"}
        )
    assert response.status_code == 403
    checker.check.assert_not_awaited()

    app, checker = _api(monkeypatch, role=RoleEnum.admin)
    with TestClient(app) as client:
        unknown = client.post(
            "/system/connections/check", json={"connection_id": "gone"}
        )
        result = client.post(
            "/system/connections/check", json={"connection_id": "broker"}
        )
    assert unknown.status_code == 404
    assert result.status_code == 200
    body = result.json()
    assert body["connection_id"] == "broker"
    assert body["status"] == "blocked"
    assert set(body) == {
        "connection_id",
        "status",
        "message",
        "latency_ms",
        "checked_at",
    }


async def test_gateway_forwards_the_check_with_the_member_token(monkeypatch):
    request = AsyncMock(return_value={})
    monkeypatch.setattr(gateway.tactic, "request", request)
    await gateway.check_connection(
        SystemConnectionCheckScope(connection_id="broker"), "Bearer token"
    )
    request.assert_awaited_with(
        "POST",
        "/api/v1/system/connections/check",
        json_data={"connection_id": "broker"},
        headers={"Authorization": "Bearer token"},
    )
