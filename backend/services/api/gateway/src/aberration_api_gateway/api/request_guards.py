"""Limits every request meets before routing, authentication or logging.

Both run ahead of FastAPI's dependency resolution, so they also bound anonymous
requests to protected routes, which are rejected only after their body is read
and which would otherwise each write a security log line.
"""

import json
import time
from collections.abc import Callable

from aberration_core.schemas.dojo import MAX_UPLOAD_BYTES
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .rate_limiter import client_ip

# JSON bodies are small; only the Dojo CSV import carries a file.
DEFAULT_MAX_BODY_BYTES = 1024 * 1024
UPLOAD_PATHS = {("POST", "/v1/dojo/datasets/csv"): MAX_UPLOAD_BYTES}

# Generous for a dashboard behind one NAT address, small enough that one client
# cannot dominate the gateway or the log pipeline behind it.
CLIENT_REQUESTS_PER_WINDOW = 1200
CLIENT_WINDOW_SECONDS = 60.0
MAX_TRACKED_CLIENTS = 10_000


def _route_path(scope: Scope) -> str:
    root = scope.get("root_path", "")
    path = scope.get("path", "")
    return path[len(root) :] if root and path.startswith(root) else path


async def _send_json(send: Send, status: int, detail: str, headers=()) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                *headers,
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class _BodyTooLarge(Exception):
    pass


def _declared_length_refusal(scope: Scope, limit: int) -> tuple[int, str] | None:
    declared = dict(scope["headers"]).get(b"content-length")
    if declared is None:
        return None
    try:
        size = int(declared)
    except ValueError:
        return 400, "Invalid Content-Length"
    return (413, "Request body too large") if size > limit else None


class BodySizeLimitMiddleware:
    """Refuse request bodies above the route's limit with 413.

    A declared Content-Length is checked before anything is read; a body sent
    without one is counted as it streams in.
    """

    def __init__(self, app: ASGIApp, limits: Callable[[str, str], int] | None = None):
        self.app = app
        self.limits = limits or self.limit_for

    @staticmethod
    def limit_for(method: str, path: str) -> int:
        return UPLOAD_PATHS.get((method, path.rstrip("/")), DEFAULT_MAX_BODY_BYTES)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.limits(scope["method"], _route_path(scope))
        if refusal := _declared_length_refusal(scope, limit):
            await _send_json(send, *refusal)
            return

        received = 0
        started = False

        async def counted_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counted_receive, tracked_send)
        except _BodyTooLarge:
            if started:
                raise
            await _send_json(send, 413, "Request body too large")


class ClientRateLimitMiddleware:
    """Answer 429 once a client sends more than its share in a fixed window.

    Counts every request, matched route or not, per forwarded client address.
    Route-specific slowapi limits still apply on top.
    """

    def __init__(
        self,
        app: ASGIApp,
        limit: int = CLIENT_REQUESTS_PER_WINDOW,
        window: float = CLIENT_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.app = app
        self.limit = limit
        self.window = window
        self.clock = clock
        self.windows: dict[str, tuple[float, int]] = {}

    def _admit(self, client: str) -> float | None:
        """Count one request; return seconds to wait when over the limit."""
        now = self.clock()
        start, count = self.windows.get(client, (now, 0))
        if now - start >= self.window:
            start, count = now, 0
        if count >= self.limit:
            return self.window - (now - start)
        if client not in self.windows and len(self.windows) >= MAX_TRACKED_CLIENTS:
            self.windows = {
                key: value
                for key, value in self.windows.items()
                if now - value[0] < self.window
            }
            if len(self.windows) >= MAX_TRACKED_CLIENTS:
                # Every slot is live: drop the oldest window to stay bounded.
                del self.windows[min(self.windows, key=lambda k: self.windows[k][0])]
        self.windows[client] = (start, count + 1)
        return None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        wait = self._admit(client_ip(Request(scope)))
        if wait is None:
            await self.app(scope, receive, send)
            return
        await _send_json(
            send,
            429,
            "Too many requests",
            [(b"retry-after", str(max(1, int(wait + 0.999))).encode())],
        )


__all__ = ["BodySizeLimitMiddleware", "ClientRateLimitMiddleware"]
