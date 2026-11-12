"""One-shot connection attempt telling whether a saved source would accept us today.

A check opens one socket with the connection's saved transport, TLS, credential
and proxy route. For a broker it waits for CONNACK and disconnects; for an HTTP
source it sends one GET and reads the status. It never subscribes, publishes or
records anything. Results carry fixed wording only: never exception text, host
credentials, certificates, broker payloads or reply bodies.
"""

import asyncio
import http.client
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
from .broker_access import ResolvedBroker, ResolvedHttpSource, peer, resolve_broker
from .system_live_http import NOT_HTTP, HttpSession
from .system_live_mqtt import CREDENTIAL_REFUSALS, configure_client

_BLOCKED = {
    "host_not_allowed": "The broker is not in the operator's live host allowlist.",
    "credential_missing": (
        "The connection's private credential reference is unavailable."
    ),
}
_ORIGIN_BLOCKED = "The server is not in the operator's HTTP origin allowlist."

# Checked in order: specific socket errors precede their OSError base class.
_CONNECT_FAILURES = (
    (
        ssl.SSLError,
        "tls_error",
        "The TLS handshake failed; check the port, TLS setting and certificate.",
    ),
    (socket.gaierror, "unreachable", "The {peer} host name could not be resolved."),
    (TimeoutError, "timeout", "The {peer} did not respond in time."),
    (
        WebsocketConnectionError,
        "refused",
        "The server did not accept the MQTT WebSocket upgrade; check the path.",
    ),
    (
        ProxyError,
        "unreachable",
        "The {peer} could not be reached through the operator's proxy.",
    ),
    (
        ConnectionRefusedError,
        "unreachable",
        "Nothing accepts connections on this host and port.",
    ),
    (OSError, "unreachable", "The {peer} host could not be reached."),
)
_TLS_TIMEOUT = (
    "The {peer} did not complete the TLS handshake in time; "
    "check the port and TLS setting."
)
_SILENT = "The broker accepted the socket but did not answer MQTT in time."
_CLOSED = "The broker closed the connection without accepting MQTT."


def _connect_failure(error: OSError, connection) -> tuple[str, str]:
    if isinstance(error, TimeoutError) and connection.tls:
        return "timeout", _TLS_TIMEOUT.format(peer=peer(connection))
    return next(
        (status, message.format(peer=peer(connection)))
        for kind, status, message in _CONNECT_FAILURES
        if isinstance(error, kind)
    )


def _answer(reason, latency_ms: int) -> tuple[str, str | None, int | None]:
    if not reason.is_failure:
        return "reachable", None, latency_ms
    if getattr(reason, "value", None) in CREDENTIAL_REFUSALS:
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
        return *_connect_failure(error, connection), None
    finally:
        # DISCONNECT is written synchronously without a network thread; any
        # remaining socket (a refused or silent peer) is closed here.
        client.disconnect()
        leftover = client.socket()
        if leftover is not None:
            leftover.close()
    return _answer(replies[0], round((clock() - started) * 1000))


def probe_http(
    resolved: ResolvedHttpSource,
    path: str | None,
    timeout: float,
    *,
    session_factory=HttpSession,
    clock=time.monotonic,
) -> tuple[str, str | None, int | None]:
    """One blocking GET; returns (status, message, latency_ms).

    ``path`` is the request path of a reading. Without one the root is asked and
    any HTTP answer shows the server is there. A reply is read up to the payload
    limit and discarded.
    """
    session = session_factory(
        resolved.connection, resolved.credential, resolved.proxy, timeout=timeout
    )
    started = clock()
    try:
        status, _, _ = session.get(path or "/", timeout)
    except http.client.HTTPException:
        return "refused", NOT_HTTP, None
    except OSError as error:
        return *_connect_failure(error, resolved.connection), None
    finally:
        session.close()
    latency = round((clock() - started) * 1000)
    if 200 <= status < 300:
        return "reachable", None, latency
    if status == 401:
        return (
            "auth_rejected",
            "The server answered but rejected the saved credentials.",
            None,
        )
    if path is None:
        return (
            "reachable",
            f"The server answered HTTP {status} at /. Add a reading to check "
            "its request path.",
            latency,
        )
    return (
        "refused",
        f"The server answered HTTP {status} at the request path of its first reading.",
        None,
    )


class BrokerCheck:
    """Bounded, on-demand source reachability checks for administrators."""

    def __init__(
        self,
        settings: SystemLiveSettings,
        *,
        access_resolver=None,
        client_factory=Client,
        session_factory=HttpSession,
        clock=time.monotonic,
    ):
        self.settings = settings
        self.access_resolver = access_resolver
        self.client_factory = client_factory
        self.session_factory = session_factory
        self.clock = clock
        # Each check holds a worker thread for at most the timeout.
        self.slots = asyncio.Semaphore(settings.SYSTEM_CONNECTION_CHECK_CONCURRENCY)

    async def check(
        self, connection: SystemConnection, *, path: str | None = None
    ) -> SystemConnectionCheck:
        """``path`` is the request path an HTTP source is asked for."""
        access = self.access_resolver(connection) if self.access_resolver else None
        resolved = resolve_broker(self.settings, connection, access)
        if isinstance(resolved, str):
            blocked = connection.protocol == "http" and resolved == "host_not_allowed"
            message = _ORIGIN_BLOCKED if blocked else _BLOCKED[resolved]
            return self._result(connection, "blocked", message)
        timeout = self.settings.SYSTEM_CONNECTION_CHECK_TIMEOUT_SECONDS
        async with self.slots:
            if isinstance(resolved, ResolvedHttpSource):
                attempt = asyncio.to_thread(
                    probe_http,
                    resolved,
                    path,
                    timeout,
                    session_factory=self.session_factory,
                    clock=self.clock,
                )
            else:
                attempt = asyncio.to_thread(
                    probe,
                    resolved,
                    timeout,
                    client_factory=self.client_factory,
                    clock=self.clock,
                )
            status, message, latency = await attempt
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
