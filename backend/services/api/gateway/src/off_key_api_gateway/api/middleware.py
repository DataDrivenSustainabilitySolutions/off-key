import time
from collections.abc import Callable

from fastapi import Request, Response
from off_key_core.config.logging import get_logging_settings
from off_key_core.config.logs import (
    log_performance,
    logger,
    redact_ip_address,
    redact_query_params,
)
from starlette.middleware.base import BaseHTTPMiddleware

from .rate_limiter import client_ip as forwarded_client_ip


def _safe_user_agent(request: Request) -> str:
    user_agent = request.headers.get("user-agent", "unknown")
    return user_agent if len(user_agent) <= 120 else f"{user_agent[:117]}..."


SUSPICIOUS_PATTERNS = (
    "admin",
    "config",
    ".env",
    "backup",
    "sql",
    "script",
    "passwd",
    "shadow",
    "etc/",
    "var/",
    "proc/",
    "sys/",
    "../",
    "..\\",
    "eval(",
    "exec(",
    "<script",
)
SECURITY_STATUS_EVENTS = {
    401: "event=security.authentication_failed ip=%s path=%s suppressed=%s",
    403: "event=security.authorization_failed ip=%s path=%s suppressed=%s",
}


# One client probing or replaying bad tokens must not flood the log pipeline:
# each (event, client) pair logs its first occurrence in a window, and the next
# logged line carries how many were left out in between.
SECURITY_LOG_WINDOW_SECONDS = 60.0
MAX_TRACKED_SECURITY_KEYS = 10_000


class SecurityEventThrottle:
    def __init__(
        self,
        window: float = SECURITY_LOG_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.window = window
        self.clock = clock
        self.seen: dict[tuple[str, str], tuple[float, int]] = {}

    def admit(self, event: str, client: str) -> int | None:
        """Return the suppressed count to report, or None to skip this line."""
        now = self.clock()
        key = (event, client)
        if key in self.seen:
            start, suppressed = self.seen[key]
            if now - start < self.window:
                self.seen[key] = (start, suppressed + 1)
                return None
        elif len(self.seen) >= MAX_TRACKED_SECURITY_KEYS:
            self.seen = {k: v for k, v in self.seen.items() if now - v[0] < self.window}
            if len(self.seen) >= MAX_TRACKED_SECURITY_KEYS:
                return None
        suppressed = self.seen.get(key, (now, 0))[1]
        self.seen[key] = (now, 0)
        return suppressed


# Only security events and failures log these, so they are built on demand.
def _client_ip(request: Request) -> str:
    return redact_ip_address(forwarded_client_ip(request))


def _safe_query(request: Request) -> dict:
    return redact_query_params(dict(request.query_params))


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log each request and its security events.

    CorrelationIdMiddleware has already bound the request's ID.
    """

    def __init__(self, app, security_events: SecurityEventThrottle | None = None):
        super().__init__(app)
        self.security_events = security_events or SecurityEventThrottle()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        settings = get_logging_settings()
        start_time = time.time()
        method = request.method
        path = request.url.path
        safe_user_agent = _safe_user_agent(request)
        lowered_path = path.lower()

        if any(pattern in lowered_path for pattern in SUSPICIOUS_PATTERNS):
            client = _client_ip(request)
            suppressed = self.security_events.admit("suspicious_request", client)
            if suppressed is not None:
                logger.warning(
                    "event=security.suspicious_request ip=%s method=%s "
                    "path=%s user_agent=%s suppressed=%s",
                    client,
                    method,
                    path,
                    safe_user_agent,
                    suppressed,
                )

        try:
            response = await call_next(request)
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.exception(
                "event=http.request_failed method=%s path=%s "
                "duration_ms=%.2f query=%s user_agent=%s error=%s",
                method,
                path,
                duration_ms,
                _safe_query(request),
                safe_user_agent,
                str(e),
            )
            raise

        duration_ms = (time.time() - start_time) * 1000
        if settings.ENABLE_PERFORMANCE_LOGGING:
            log_performance(f"{method} {path}", start_time)
        if settings.ENABLE_REQUEST_LOGGING:
            logger.info(
                "event=http.request method=%s path=%s status=%s "
                "duration_ms=%.2f query=%s user_agent=%s",
                method,
                path,
                response.status_code,
                duration_ms,
                _safe_query(request),
                safe_user_agent,
            )
        if event := SECURITY_STATUS_EVENTS.get(response.status_code):
            client = _client_ip(request)
            suppressed = self.security_events.admit(event, client)
            if suppressed is not None:
                logger.warning(event, client, path, suppressed)
        return response


__all__ = ["RequestLoggingMiddleware"]
