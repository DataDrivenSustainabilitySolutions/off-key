"""A loopback HTTP source and a blocking wait for polling tests."""

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


@dataclass
class Reply:
    status: int = 200
    body: bytes = b"{}"
    headers: dict = field(default_factory=dict)
    delay: float = 0.0
    # Close the socket after answering without announcing it.
    hang_up: bool = False


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # Keep the socket open between requests.

    def setup(self):
        super().setup()
        self.server.connections += 1

    def log_message(self, *arguments):
        pass

    def do_GET(self):
        self.server.requests.append((self.path, dict(self.headers.items())))
        reply = self.server.routes.get(self.path, Reply(404))
        if callable(reply):
            reply = reply()
        if reply.delay:
            time.sleep(reply.delay)
        self.send_response(reply.status)
        for name, value in reply.headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(reply.body)))
        self.end_headers()
        self.wfile.write(reply.body)
        if reply.hang_up:
            self.close_connection = True


class SourceServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, routes):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.routes = dict(routes)
        self.requests: list[tuple[str, dict]] = []
        self.connections = 0

    @property
    def port(self) -> int:
        return self.server_address[1]

    def paths(self) -> list[str]:
        return [path for path, _ in self.requests]


@contextmanager
def http_source(routes=None):
    """Serve ``routes`` (request path to Reply, or to a callable returning one)."""
    server = SourceServer(routes or {})
    Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def eventually(predicate, deadline_seconds=5.0) -> None:
    """Block until a worker thread has made ``predicate`` true."""
    deadline = time.monotonic() + deadline_seconds
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("The expected state was not reached in time")
        time.sleep(0.01)
