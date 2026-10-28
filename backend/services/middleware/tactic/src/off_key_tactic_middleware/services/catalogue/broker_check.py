"""One-shot MQTT CONNECT telling whether a saved broker would accept us today.

A check opens one socket with the connection's saved transport, TLS, credential
and proxy route, waits for CONNACK, and disconnects. It never subscribes,
publishes or records anything. Results carry fixed wording only: never
exception text, host credentials, certificates or broker payloads.
"""

import asyncio
import math
import socket
import ssl
import time
from datetime import UTC, datetime
from uuid import uuid4

from off_key_core.schemas.system import SystemConnection, SystemConnectionCheck
from paho.mqtt.client import MQTT_ERR_SUCCESS, Client, WebsocketConnectionError
from paho.mqtt.enums import CallbackAPIVersion
from socks import ProxyError

from ...config.system_live import SystemLiveSettings
from .broker_access import ResolvedBroker, resolve_broker
from .system_live_mqtt import configure_client

# CONNACK refusals that mean "these credentials", as Callback API v2 maps both
# MQTT 3.1.1 return codes 4/5 and MQTT 5 reason codes onto them.
_AUTH_REFUSALS = {134, 135}

_BLOCKED = {
    "host_not_allowed": "The broker is not in the operator's live host allowlist.",
    "credential_missing": (
        "The connection's private credential reference is unavailable."
    ),
}

# Checked in order: specific socket errors precede their OSError base class.
_CONNECT_FAILURES = (
    (
        ssl.SSLError,
        "tls_error",
        "The TLS handshake failed; check the port, TLS setting and certificate.",
    ),
    (socket.gaierror, "unreachable", "The broker host name could not be resolved."),
    (TimeoutError, "timeout", "The broker did not respond in time."),
    (
        WebsocketConnectionError,
        "refused",
        "The server did not accept the MQTT WebSocket upgrade; check the path.",
    ),
    (
        ProxyError,
        "unreachable",
        "The broker could not be reached through the operator's proxy.",
    ),
    (
        ConnectionRefusedError,
        "unreachable",
        "Nothing accepts connections on this host and port.",
    ),
    (OSError, "unreachable", "The broker host could not be reached."),
)
_TLS_TIMEOUT = (
    "The broker did not complete the TLS handshake in time; "
    "check the port and TLS setting."
)
_SILENT = "The broker accepted the socket but did not answer MQTT in time."
_CLOSED = "The broker closed the connection without accepting MQTT."


def _connect_failure(error: OSError, tls: bool) -> tuple[str, str]:
    if isinstance(error, TimeoutError) and tls:
        return "timeout", _TLS_TIMEOUT
    return next(
        (status, message)
        for kind, status, message in _CONNECT_FAILURES
        if isinstance(error, kind)
    )


def _answer(reason, latency_ms: int) -> tuple[str, str | None, int | None]:
    if not reason.is_failure:
        return "reachable", None, latency_ms
    if getattr(reason, "value", None) in _AUTH_REFUSALS:
        return (
            "auth_rejected",
            "The broker answered but rejected the saved credentials.",
            None,
        )
    return "refused", "The broker answered but refused the connection.", None


def probe(
    resolved: ResolvedBroker,
    timeout: float,
    *,
    client_factory=Client,
    clock=time.monotonic,
) -> tuple[str, str | None, int | None]:
    """Blocking CONNECT/CONNACK round trip; returns (status, message, latency_ms)."""
    connection = resolved.connection
    client = client_factory(
        CallbackAPIVersion.VERSION2,
        client_id=f"aberration-check-{uuid4().hex}",
        clean_session=True,
        transport="websockets" if connection.transport == "websocket" else "tcp",
        reconnect_on_failure=False,
    )
    client.connect_timeout = timeout
    replies = []
    client.on_connect = lambda _c, _u, _flags, reason, _p: replies.append(reason)
    configure_client(client, connection, resolved.credential, resolved.proxy)
    started = clock()
    deadline = started + timeout
    try:
        # Paho bounds the TLS and WebSocket handshakes by the keepalive interval.
        client.connect(connection.host, connection.port, keepalive=math.ceil(timeout))
        while not replies:
            remaining = deadline - clock()
            if remaining <= 0:
                return "timeout", _SILENT, None
            # A refusing CONNACK reaches on_connect before loop() reports it.
            failed = client.loop(timeout=min(remaining, 0.25)) != MQTT_ERR_SUCCESS
            if failed and not replies:
                return "refused", _CLOSED, None
    except OSError as error:
        return *_connect_failure(error, connection.tls), None
    finally:
        # DISCONNECT is written synchronously without a network thread; any
        # remaining socket (a refused or silent peer) is closed here.
        client.disconnect()
        leftover = client.socket()
        if leftover is not None:
            leftover.close()
    return _answer(replies[0], round((clock() - started) * 1000))


class BrokerCheck:
    """Bounded, on-demand broker reachability checks for administrators."""

    def __init__(
        self,
        settings: SystemLiveSettings,
        *,
        access_resolver=None,
        client_factory=Client,
        clock=time.monotonic,
    ):
        self.settings = settings
        self.access_resolver = access_resolver
        self.client_factory = client_factory
        self.clock = clock
        # Each check holds a worker thread for at most the timeout.
        self.slots = asyncio.Semaphore(settings.SYSTEM_CONNECTION_CHECK_CONCURRENCY)

    async def check(self, connection: SystemConnection) -> SystemConnectionCheck:
        access = self.access_resolver(connection) if self.access_resolver else None
        resolved = resolve_broker(self.settings, connection, access)
        if isinstance(resolved, str):
            return self._result(connection, "blocked", _BLOCKED[resolved])
        async with self.slots:
            status, message, latency = await asyncio.to_thread(
                probe,
                resolved,
                self.settings.SYSTEM_CONNECTION_CHECK_TIMEOUT_SECONDS,
                client_factory=self.client_factory,
                clock=self.clock,
            )
        return self._result(connection, status, message, latency)

    @staticmethod
    def _result(connection, status, message, latency_ms=None) -> SystemConnectionCheck:
        return SystemConnectionCheck(
            connection_id=connection.id,
            status=status,
            message=message,
            latency_ms=latency_ms,
            checked_at=datetime.now(UTC),
        )
