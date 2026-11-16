"""Prometheus metrics on a private port, for the scraper in the observability stack.

A service serves metrics only when its entry point asks for them and
``METRICS_PORT`` names a port. The port is never routed by the frontend or
Traefik, so metrics stay inside the stack networks. Child processes that call
the shared bootstrap without asking (RADAR monitors under the pool) never bind
it, even though they inherit the variable.
"""

import os
import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from prometheus_client import Counter, Histogram, start_http_server

from off_key_core.config.logs import logger

METRICS_PORT_ENV = "METRICS_PORT"

HTTP_REQUESTS = Counter(
    "offkey_http_requests",
    "HTTP requests answered, by route template and status class.",
    ["service", "method", "route", "status"],
)
HTTP_DURATION = Histogram(
    "offkey_http_request_duration_seconds",
    "Time to answer an HTTP request, by route template.",
    ["service", "method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)

_started: int | None = None


def metrics_port() -> int | None:
    """The configured metrics port, or None when metrics are switched off."""
    raw = os.environ.get(METRICS_PORT_ENV, "").strip()
    if not raw:
        return None
    try:
        port = int(raw)
    except ValueError as error:
        raise ValueError(f"{METRICS_PORT_ENV} must be a port number") from error
    if port == 0:
        return None
    if not 1024 <= port <= 65535:
        raise ValueError(f"{METRICS_PORT_ENV} must be 0 or between 1024 and 65535")
    return port


def start_metrics_server(service: str) -> int | None:
    """Serve ``/metrics`` once per process; returns the bound port, if any."""
    global _started
    port = metrics_port()
    if port is None or _started is not None:
        return _started
    start_http_server(port, addr="0.0.0.0")
    _started = port
    logger.info("event=metrics.serving service=%s port=%d", service, port)
    return port


Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
App = Callable[[Scope, Receive, Send], Awaitable[None]]


class HttpMetricsMiddleware:
    """Count requests and their duration by route template, never by raw path.

    Raw paths carry identifiers, which would give every monitor or user its own
    time series. Unmatched paths are counted together.
    """

    def __init__(self, app: App, *, service: str):
        self.app = app
        self.service = service

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status = 500
        started = time.perf_counter()

        async def observe(message: MutableMapping[str, Any]) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, observe)
        finally:
            route = getattr(scope.get("route"), "path", None) or "unmatched"
            method = scope.get("method", "GET")
            HTTP_REQUESTS.labels(
                self.service, method, route, f"{status // 100}xx"
            ).inc()
            HTTP_DURATION.labels(self.service, method, route).observe(
                time.perf_counter() - started
            )
