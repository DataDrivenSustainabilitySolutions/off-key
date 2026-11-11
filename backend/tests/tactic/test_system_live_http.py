"""The HTTP polling worker: what it asks, what it hands on and when it gives up."""

import socket
import socketserver
import time
from threading import Thread

import pytest
from off_key_core.schemas.system import SystemConnection
from off_key_core.utils.payload_decode import MAX_PAYLOAD_BYTES
from off_key_tactic_middleware.config.system_live import (
    HttpCredential,
    LiveSocksProxy,
    SystemLiveSettings,
)
from off_key_tactic_middleware.services.catalogue import system_live_http
from off_key_tactic_middleware.services.catalogue.system_live_http import (
    NOT_HTTP,
    TLS_FAILED,
    HttpPollWorker,
    HttpSession,
)

from tests.support.http_source import Reply, eventually, http_source

pytestmark = pytest.mark.timeout(20)


def _connection(port, **fields):
    return SystemConnection(
        id="api", label="API", protocol="http", host="127.0.0.1", port=port, **fields
    )


def _worker(port, topics, **options):
    messages, states = [], []
    worker = HttpPollWorker(
        _connection(port, **options.pop("connection", {})),
        topics,
        options.pop("credential", None),
        lambda address, payload, retained: messages.append(
            (address, payload, retained)
        ),
        lambda phase, message: states.append((phase, message)),
        **options,
    )
    return worker, messages, states


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_each_path_is_polled_at_its_interval_over_one_socket():
    routes = {
        "/status?unit=%C2%B0C": Reply(body=b'{"temperature": 21.5}'),
        "/slow": Reply(body=b"7"),
    }
    with http_source(routes) as server:
        worker, messages, states = _worker(
            server.port, {"/status?unit=°C": 0.05, "/slow": 60}
        )
        worker.start()
        eventually(lambda: len(messages) >= 4)
        worker.stop()

        assert not worker.thread.is_alive()
        assert server.paths().count("/slow") == 1
        assert ("/status?unit=°C", b'{"temperature": 21.5}', False) in messages
        assert ("/slow", b"7", False) in messages
        assert states == [("connecting", None), ("connected", None)]
        assert server.connections == 1


@pytest.mark.parametrize(
    ("credential", "header", "value"),
    [
        ({"token": "abc"}, "Authorization", "Bearer abc"),
        (
            {"username": "reader", "password": "secret"},
            "Authorization",
            "Basic cmVhZGVyOnNlY3JldA==",
        ),
        ({"token": "key-1", "header": "X-API-Key"}, "X-Api-Key", "key-1"),
        (
            {"token": "Token abc", "header": "Authorization"},
            "Authorization",
            "Token abc",
        ),
    ],
)
def test_a_credential_becomes_one_request_header(credential, header, value):
    with http_source({"/": Reply()}) as server:
        session = HttpSession(
            _connection(server.port), HttpCredential(**credential), None
        )
        assert session.get("/")[0] == 200
        session.close()
        sent = {name.lower(): text for name, text in server.requests[0][1].items()}
        assert sent[header.lower()] == value


@pytest.mark.parametrize(
    "credential",
    [
        {},
        {"token": "abc", "password": "also"},
        {"username": "reader", "password": "secret", "header": "X-API-Key"},
        {"token": "abc", "header": "Host"},
        {"token": "abc\r\nX-Injected: 1"},
        {"token": "abc", "header": "Bad Header"},
    ],
)
def test_a_credential_names_exactly_one_safe_login(credential):
    with pytest.raises(ValueError):
        HttpCredential(**credential)


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "The server rejected the connection credentials."),
        (403, "The server denied access to a configured request path."),
    ],
)
def test_a_rejected_login_is_not_sent_again(status, message):
    with http_source({"/a": Reply(status), "/b": Reply()}) as server:
        worker, _, states = _worker(server.port, {"/a": 0.05, "/b": 0.05})
        worker.start()
        eventually(lambda: not worker.thread.is_alive())

        assert states[-1] == ("error", message)
        assert worker.denied
        assert not worker.update_topics(["/b"])
        asked = len(server.requests)
        time.sleep(0.2)
        assert len(server.requests) == asked
        worker.stop()


def test_a_redirect_is_reported_and_never_followed():
    routes = {"/old": Reply(302, headers={"Location": "/new"}), "/new": Reply()}
    with http_source(routes) as server:
        worker, messages, states = _worker(server.port, {"/old": 0.05})
        worker.start()
        eventually(lambda: not worker.thread.is_alive())
        worker.stop()

        assert messages == []
        assert server.paths() == ["/old"]
        assert states[-1] == (
            "error",
            "The server answered HTTP 302 instead of data at every request path.",
        )


def test_one_missing_path_does_not_stop_the_others():
    with http_source({"/ok": Reply(body=b"1")}) as server:
        worker, messages, states = _worker(server.port, {"/ok": 0.05, "/gone": 0.05})
        worker.start()
        eventually(
            lambda: (
                states[-1] == ("connected", "1 of 2 request paths return no data.")
                and len(messages) >= 3
            )
        )
        worker.stop()

        assert {address for address, _, _ in messages} == {"/ok"}
        # A failing path is asked less and less often.
        assert server.paths().count("/gone") < server.paths().count("/ok")


def test_a_failing_server_is_retried_until_it_answers_with_data():
    answers = [Reply(503), Reply(503, headers={"Retry-After": "0"})]
    with http_source() as server:
        server.routes["/a"] = lambda: answers.pop(0) if answers else Reply(body=b"1")
        worker, messages, states = _worker(server.port, {"/a": 0.05})
        worker.start()
        eventually(lambda: messages)
        worker.stop()

        assert states == [
            ("connecting", None),
            (
                "reconnecting",
                "The server answers with errors; retrying with bounded backoff.",
            ),
            ("connected", None),
        ]


def test_an_unreachable_server_is_retried_quietly():
    worker, _, states = _worker(_closed_port(), {"/a": 0.05})
    worker.start()
    eventually(lambda: len(states) == 2)
    time.sleep(0.1)
    worker.stop()

    assert states == [
        ("connecting", None),
        ("reconnecting", "Server unavailable; retrying with bounded backoff."),
    ]


def test_tls_to_a_plain_port_is_named():
    with http_source({"/a": Reply()}) as server:
        worker, _, states = _worker(server.port, {"/a": 0.05}, connection={"tls": True})
        worker.start()
        eventually(lambda: len(states) == 2)
        worker.stop()
        assert states[-1] == ("reconnecting", TLS_FAILED)


def test_a_peer_that_does_not_speak_http_is_named():
    class Garbage(socketserver.BaseRequestHandler):
        def handle(self):
            self.request.recv(1024)
            self.request.sendall(b"\x15\x03\x01\x00\x02\x02\x16")

    with socketserver.TCPServer(("127.0.0.1", 0), Garbage) as server:
        Thread(target=server.serve_forever, daemon=True).start()
        worker, _, states = _worker(server.server_address[1], {"/a": 0.05})
        worker.start()
        eventually(lambda: len(states) == 2)
        worker.stop()
        server.shutdown()
    assert states[-1] == ("reconnecting", NOT_HTTP)


def test_a_reply_is_cut_just_past_the_payload_limit():
    large = Reply(body=b"x" * (MAX_PAYLOAD_BYTES + 5000))
    with http_source({"/large": large, "/small": Reply(body=b"1")}) as server:
        session = HttpSession(_connection(server.port), None, None)
        status, body, _ = session.get("/large")
        assert (status, len(body)) == (200, MAX_PAYLOAD_BYTES + 1)
        # The unread remainder is discarded with its socket.
        assert session.get("/small")[1] == b"1"
        session.close()
        assert server.connections == 2


@pytest.mark.parametrize(
    "reply",
    [
        Reply(body=b"1", headers={"Connection": "close"}),
        Reply(body=b"1", hang_up=True),
    ],
    ids=["announced", "unannounced"],
)
def test_a_socket_the_server_closed_is_replaced(reply):
    with http_source({"/a": reply}) as server:
        session = HttpSession(_connection(server.port), None, None)
        for _ in range(3):
            assert session.get("/a")[1] == b"1"
            time.sleep(0.05)  # Let the server finish closing its side.
        session.close()
        assert server.connections == 3


def test_stop_ends_a_request_that_is_still_waiting():
    with http_source({"/stalled": Reply(delay=30)}) as server:
        worker, _, _ = _worker(server.port, {"/stalled": 1})
        worker.start()
        eventually(lambda: server.requests)
        started = time.monotonic()
        worker.stop()

        assert time.monotonic() - started < 3
        assert not worker.thread.is_alive()


def test_a_changed_scope_is_polled_without_reconnecting():
    with http_source({"/a": Reply(body=b"a"), "/b": Reply(body=b"b")}) as server:
        worker, messages, states = _worker(server.port, ["/a"], interval=0.05)
        worker.start()
        eventually(lambda: messages)
        assert worker.update_topics(["/b"])
        eventually(lambda: messages[-1][0] == "/b")
        seen = len(messages)
        eventually(lambda: len(messages) >= seen + 2)
        worker.stop()

        assert {address for address, _, _ in messages[seen:]} == {"/b"}
        assert worker.topics == ["/b"]
        assert states == [("connecting", None), ("connected", None)]
        assert server.connections == 1


def test_requests_take_the_operators_socks_route(monkeypatch):
    routed = []

    def through_proxy(address, timeout, **options):
        routed.append((address, options))
        return socket.create_connection(address, timeout)

    monkeypatch.setattr(system_live_http, "proxied_connection", through_proxy)
    proxy = LiveSocksProxy(host="route", port=1055, username="u", password="p")
    with http_source({"/": Reply()}) as server:
        session = HttpSession(_connection(server.port), None, proxy)
        assert session.get("/")[0] == 200
        session.close()

    address, options = routed[0]
    assert address == ("127.0.0.1", server.port)
    assert (options["proxy_addr"], options["proxy_port"]) == ("route", 1055)
    assert options["proxy_rdns"] is True
    assert (options["proxy_username"], options["proxy_password"]) == ("u", "p")


@pytest.mark.parametrize(
    ("origin", "saved"),
    [
        ("https://API.Example.com", "https://api.example.com:443"),
        ("http://10.0.0.7:8080/", "http://10.0.0.7:8080"),
        ("http://[2001:db8::1]", "http://[2001:db8::1]:80"),
    ],
)
def test_allowed_origins_fix_scheme_host_and_port(origin, saved):
    settings = SystemLiveSettings(SYSTEM_HTTP_ALLOWED_ORIGINS=[origin])
    assert [saved] == settings.SYSTEM_HTTP_ALLOWED_ORIGINS


@pytest.mark.parametrize(
    "origin",
    [
        "api.example.com:443",
        "mqtt://broker.example.com",
        "https://user:secret@api.example.com",
        "https://api.example.com/v1",
        "https://api.example.com?key=1",
        "https://api.example.com:0",
        "https://api.example.com:99999",
        "https://",
    ],
)
def test_an_origin_is_only_a_scheme_host_and_port(origin):
    with pytest.raises(ValueError):
        SystemLiveSettings(SYSTEM_HTTP_ALLOWED_ORIGINS=[origin])


def test_http_credentials_are_read_from_one_private_json_value(monkeypatch):
    monkeypatch.setenv(
        "SYSTEM_HTTP_CREDENTIALS", '{"credentials/weather":{"token":"abc"}}'
    )
    monkeypatch.setenv("SYSTEM_HTTP_ALLOWED_ORIGINS", '["https://api.example.com"]')
    settings = SystemLiveSettings()

    credential = settings.SYSTEM_HTTP_CREDENTIALS["credentials/weather"]
    assert credential.request_header() == ("Authorization", "Bearer abc")
    assert "abc" not in repr(settings.SYSTEM_HTTP_CREDENTIALS)
    assert settings.allows_origin(
        SystemConnection(
            id="api",
            label="API",
            protocol="http",
            host="api.example.com",
            tls=True,
        )
    )
