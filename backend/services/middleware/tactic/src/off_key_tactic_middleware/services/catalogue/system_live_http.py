"""One polling thread per approved HTTP source, behind the MQTT worker's contract.

A worker sends GET requests to the saved host and port only, one request path at
a time, and hands each reply to ``on_message`` as an MQTT worker hands over a
message. Redirects are not followed, replies are cut at the payload limit, and
public state uses fixed wording: never a reply, header, credential or exception.
"""

import http.client
import socket
import ssl
import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from threading import Event, RLock, Thread, current_thread
from urllib.parse import quote

from off_key_core.schemas.system import SystemConnection
from off_key_core.utils.payload_decode import MAX_PAYLOAD_BYTES
from socks import SOCKS5
from socks import create_connection as proxied_connection

from ...config.system_live import HttpCredential, LiveSocksProxy

# One socket operation and one whole request, in seconds.
SOCKET_TIMEOUT = 5.0
REQUEST_TIMEOUT = 10.0
# A socket idle for longer is closed instead of kept for the next poll.
KEEP_ALIVE_SECONDS = 15.0
# A path that keeps failing is asked less often, up to this pause.
MAX_PATH_BACKOFF_SECONDS = 300.0
MAX_OUTAGE_BACKOFF_SECONDS = 30.0
# Characters a saved request path may carry unescaped; the rest is UTF-8 encoded.
_PATH_CHARACTERS = "/?&=%:@!$'()*,;[]~"

TLS_FAILED = "The TLS handshake failed; check the port, TLS setting and certificate."
NOT_HTTP = "The server did not answer with HTTP; check the port and TLS setting."


class HttpSession:
    """A kept-alive connection to one source; a request reopens it when needed."""

    def __init__(
        self,
        connection: SystemConnection,
        credential: HttpCredential | None,
        proxy: LiveSocksProxy | None,
        *,
        timeout: float = SOCKET_TIMEOUT,
    ):
        self.host = connection.host
        self.port = connection.port
        # Default trust store, server hostname checks, no insecure TLS option.
        self.tls = ssl.create_default_context() if connection.tls else None
        self.proxy = proxy
        self.timeout = timeout
        self.headers = {
            "Accept": "application/json, text/plain;q=0.8, */*;q=0.1",
            "User-Agent": "aberration",
        }
        if credential is not None:
            name, value = credential.request_header()
            self.headers[name] = value
        self.link: http.client.HTTPConnection | None = None
        self.socket: socket.socket | None = None
        self.aborted = False

    def _open(self) -> http.client.HTTPConnection:
        address = (self.host, self.port)
        if self.proxy is None:
            raw = socket.create_connection(address, self.timeout)
        else:
            raw = proxied_connection(
                address,
                self.timeout,
                proxy_type=SOCKS5,
                proxy_addr=self.proxy.host,
                proxy_port=self.proxy.port,
                proxy_rdns=True,
                proxy_username=self.proxy.username or None,
                proxy_password=self.proxy.password.get_secret_value() or None,
            )
        self.socket = raw
        if self.tls is not None:
            try:
                raw = self.tls.wrap_socket(raw, server_hostname=self.host)
            except BaseException:
                raw.close()
                raise
            self.socket = raw
        link = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        link.sock = raw
        return link

    def _ask(self, target: str) -> http.client.HTTPResponse:
        while True:
            if self.aborted:
                raise ConnectionAbortedError
            reused = self.link is not None and self.link.sock is not None
            if not reused:
                self.close()
                self.link = self._open()
            try:
                self.link.request("GET", target, headers=self.headers)
                return self.link.getresponse()
            except (OSError, http.client.HTTPException):
                self.close()
                if not reused:
                    raise
                # The server closed an idle socket; ask once on a new one.
            except BaseException:
                self.close()
                raise

    def get(
        self, path: str, timeout: float = REQUEST_TIMEOUT
    ) -> tuple[int, bytes, float | None]:
        """One GET: (status, reply cut after the payload limit, Retry-After).

        Raises OSError or http.client.HTTPException when no reply arrives.
        """
        deadline = time.monotonic() + timeout
        reply = self._ask(quote(path, safe=_PATH_CHARACTERS))
        try:
            body = bytearray()
            while len(body) <= MAX_PAYLOAD_BYTES:
                if time.monotonic() >= deadline:
                    raise TimeoutError
                chunk = reply.read1(min(16384, MAX_PAYLOAD_BYTES + 1 - len(body)))
                if not chunk:
                    break
                body += chunk
            wait = reply.getheader("Retry-After", "")
        except BaseException:
            self.close()
            raise
        if not reply.isclosed():
            self.close()  # An unread remainder would be taken for the next reply.
        return reply.status, bytes(body), float(wait) if wait.isdecimal() else None

    def close(self) -> None:
        link, self.link, self.socket = self.link, None, None
        if link is not None:
            link.close()

    def abort(self) -> None:
        """Called from another thread: end a request that is waiting on the
        socket, and send no further one."""
        self.aborted = True
        waiting = self.socket
        if waiting is not None:
            with suppress(OSError):
                waiting.shutdown(socket.SHUT_RDWR)


class HttpPollWorker:
    """Polls each request path at its interval; ``topics`` maps path to seconds,
    and a plain list polls every path at ``interval``."""

    def __init__(
        self,
        connection: SystemConnection,
        topics: Mapping[str, float] | list[str],
        credential: HttpCredential | None,
        on_message: Callable,
        on_state: Callable,
        *,
        proxy: LiveSocksProxy | None = None,
        interval: float = 5.0,
        session_factory=HttpSession,
        clock=time.monotonic,
    ):
        self.connection = connection
        self.on_message = on_message
        self.on_state = on_state
        self.interval = interval
        self.clock = clock
        self.session = session_factory(connection, credential, proxy)
        self.guard = RLock()
        self.intervals = self._intervals(topics)
        self.due = dict.fromkeys(self.intervals, 0.0)
        # The last HTTP status of each path, and how often it failed in a row.
        self.statuses: dict[str, int] = {}
        self.failures: dict[str, int] = {}
        self.reported: tuple[str, str | None] | None = None
        self.denied = False
        self.stopping = Event()
        self.thread = Thread(target=self._run, name="http-source", daemon=True)

    @property
    def topics(self) -> list[str]:
        return list(self.intervals)

    def _intervals(self, topics) -> dict[str, float]:
        if isinstance(topics, Mapping):
            return {address: float(seconds) for address, seconds in topics.items()}
        return dict.fromkeys(topics, float(self.interval))

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stopping.set()
        self.session.abort()
        if self.thread.ident is not None and current_thread() is not self.thread:
            self.thread.join(timeout=REQUEST_TIMEOUT)

    def update_topics(self, topics) -> bool:
        """Change the polled paths without closing a healthy connection."""
        with self.guard:
            if self.stopping.is_set() or self.denied:
                return False
            self.intervals = self._intervals(topics)
            self.due = {key: self.due.get(key, 0.0) for key in self.intervals}
            for memory in (self.statuses, self.failures):
                for address in memory.keys() - self.intervals.keys():
                    del memory[address]
            return True

    def _say(self, phase: str, message: str | None) -> None:
        if not self.stopping.is_set() and self.reported != (phase, message):
            self.reported = (phase, message)
            self.on_state(phase, message)

    def _give_up(self, message: str) -> None:
        # The owner decides when to try again: ingress retries after its
        # backoff, a settings change or a reconnect starts a new worker.
        self.denied = True
        self._say("error", message)

    def _next(self) -> tuple[str | None, float]:
        """The path to ask now, or how long until one is due."""
        with self.guard:
            now = self.clock()
            if not self.due:
                return None, 0.5
            address = min(self.due, key=self.due.__getitem__)
            return (
                (address, 0.0)
                if self.due[address] <= now
                else (
                    None,
                    self.due[address] - now,
                )
            )

    def _run(self) -> None:
        self._say("connecting", None)
        outage = 1.0
        try:
            while not self.stopping.is_set() and not self.denied:
                address, pause = self._next()
                if address is None:
                    if pause > KEEP_ALIVE_SECONDS:
                        self.session.close()
                    # Wake regularly so a changed scope is polled without delay.
                    self.stopping.wait(min(pause, 0.5))
                    continue
                started = self.clock()
                try:
                    status, body, retry_after = self.session.get(address)
                except (OSError, http.client.HTTPException) as error:
                    self._unreachable(error, outage)
                    outage = min(outage * 2, MAX_OUTAGE_BACKOFF_SECONDS)
                    continue
                outage = 1.0
                self._settle(address, started, status, body, retry_after)
        finally:
            self.session.close()

    def _unreachable(self, error: Exception, pause: float) -> None:
        with self.guard:
            ready = self.clock() + pause
            self.due = {key: max(value, ready) for key, value in self.due.items()}
            self.statuses.clear()
        if isinstance(error, ssl.SSLError):
            self._say("reconnecting", TLS_FAILED)
        elif isinstance(error, http.client.HTTPException):
            self._say("reconnecting", NOT_HTTP)
        else:
            self._say(
                "reconnecting", "Server unavailable; retrying with bounded backoff."
            )

    def _settle(self, address, started, status, body, retry_after) -> None:
        accepted = 200 <= status < 300
        with self.guard:
            if address not in self.intervals:
                return  # The scope changed while the request was under way.
            interval = self.intervals[address]
            self.statuses[address] = status
            if accepted:
                self.failures.pop(address, None)
                pause = interval
            else:
                failed = self.failures[address] = self.failures.get(address, 0) + 1
                backoff = min(interval * 2 ** min(failed, 8), MAX_PATH_BACKOFF_SECONDS)
                pause = max(interval, backoff, min(retry_after or 0.0, 3600.0))
            # Measured from the request's start, so answers do not delay the next.
            self.due[address] = max(started + pause, self.clock())
            statuses = [self.statuses.get(key) for key in self.intervals]
        if status in (401, 403):
            self._give_up(
                "The server rejected the connection credentials."
                if status == 401
                else "The server denied access to a configured request path."
            )
            return
        if accepted and not self.stopping.is_set():
            self.on_message(address, body, False)
        answered = [code for code in statuses if code is not None]
        failing = [code for code in answered if not 200 <= code < 300]
        if len(failing) < len(answered):
            self._say(
                "connected",
                f"{len(failing)} of {len(statuses)} request paths return no data."
                if failing
                else None,
            )
        elif len(answered) < len(statuses):
            return  # Wait until every path was asked once before judging.
        elif all(code < 500 and code not in (408, 429) for code in failing):
            # Nothing here answers with data, and asking again will not change it.
            self._give_up(
                f"The server answered HTTP {failing[0]} instead of data at "
                "every request path."
            )
        else:
            self._say(
                "reconnecting",
                "The server answers with errors; retrying with bounded backoff.",
            )
