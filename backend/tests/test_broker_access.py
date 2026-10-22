"""One broker access resolution for live previews, collection ingress and saves."""

import pytest
from off_key_core.schemas.system import SystemConnection
from off_key_tactic_middleware.config.system_live import (
    LiveCredential,
    LiveSocksProxy,
    SystemLiveSettings,
)
from off_key_tactic_middleware.services.broker_access import (
    BrokerAccess,
    resolve_broker,
)

from tests.support.system_live import manager, snapshot

OPERATOR = LiveCredential(username="operator", password="operator-password")
ADAPTER = LiveCredential(username="adapter", password="adapter-password")


def _connection(host="broker", credential_ref=None):
    return SystemConnection(
        id="broker", label="Broker", host=host, credential_ref=credential_ref
    )


def _settings(**overrides):
    return SystemLiveSettings(SYSTEM_LIVE_ALLOWED_HOSTS=["broker"], **overrides)


def test_hosts_outside_the_allowlist_need_an_adapter():
    connection = _connection(host="vendor")
    adapter = BrokerAccess(credential=ADAPTER)

    assert resolve_broker(_settings(), connection, None) == "host_not_allowed"
    resolved = resolve_broker(_settings(), connection, adapter)
    assert not isinstance(resolved, str)
    assert resolved.credential == ADAPTER


def test_a_named_credential_must_exist_even_with_an_adapter():
    connection = _connection(credential_ref="absent")
    adapter = BrokerAccess(credential=ADAPTER)

    assert resolve_broker(_settings(), connection, adapter) == "credential_missing"


def test_operator_settings_win_over_the_adapter_and_tls_can_be_forced():
    settings = _settings(
        SYSTEM_LIVE_CREDENTIALS={"named": OPERATOR},
        SYSTEM_LIVE_SOCKS_PROXIES={"broker": LiveSocksProxy(host="operator-proxy")},
    )
    adapter = BrokerAccess(
        credential=ADAPTER,
        proxy=LiveSocksProxy(host="adapter-proxy"),
        require_tls=True,
    )
    connection = _connection(credential_ref="named")

    resolved = resolve_broker(settings, connection, adapter)

    assert not isinstance(resolved, str)
    assert resolved.credential == OPERATOR
    assert resolved.proxy.host == "operator-proxy"
    assert resolved.connection.tls and not connection.tls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    # Every case breaks all later checks too, so only the first one may report.
    ("overrides", "host", "credential_ref", "streams", "message"),
    [
        (
            {"SYSTEM_LIVE_MAX_CONNECTIONS": 1},
            "unapproved",
            "absent",
            65,
            "The connection exceeds the concurrent broker limit.",
        ),
        (
            {},
            "unapproved",
            "absent",
            65,
            "The broker is not in the operator's live host allowlist.",
        ),
        (
            {},
            "broker",
            "absent",
            65,
            "The connection's private credential reference is unavailable.",
        ),
        (
            {},
            "broker",
            None,
            65,
            "A topic exceeds the limit of 64 bound streams.",
        ),
    ],
)
async def test_live_checks_report_capacity_then_access_then_fanout(
    overrides, host, credential_ref, streams, message
):
    service, _ = manager(**{"SYSTEM_LIVE_MAX_CONNECTIONS": 2, **overrides})
    saved = snapshot()
    healthy, reading = saved.document.connections[0], saved.document.streams[0]
    faulty = healthy.model_copy(
        update={"id": "faulty", "host": host, "credential_ref": credential_ref}
    )
    saved.document.connections.append(faulty)
    saved.document.streams += [
        reading.model_copy(
            update={"id": f"reading-{number}", "connection_id": "faulty"}
        )
        for number in range(streams)
    ]

    data = await service.acquire(saved, 1, 1)

    states = {item["connection_id"]: item for item in data["telemetry"]["connections"]}
    assert (states["faulty"]["state"], states["faulty"]["message"]) == (
        "blocked",
        message,
    )
    assert [worker.connection.id for worker in service.workers] == ["broker"]
