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
    401: "event=security.authentication_failed ip=%s path=%s",
    403: "event=security.authorization_failed ip=%s path=%s",
}


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log each request and its security events.

    CorrelationIdMiddleware has already bound the request's ID.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        settings = get_logging_settings()
        start_time = time.time()
        method = request.method
        path = request.url.path
        client_ip = redact_ip_address(forwarded_client_ip(request))
        safe_user_agent = _safe_user_agent(request)
        safe_query = redact_query_params(dict(request.query_params))

        if any(pattern in path.lower() for pattern in SUSPICIOUS_PATTERNS):
            logger.warning(
                "event=security.suspicious_request ip=%s method=%s "
                "path=%s user_agent=%s",
                client_ip,
                method,
                path,
                safe_user_agent,
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
                safe_query,
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
                safe_query,
                safe_user_agent,
            )
        if event := SECURITY_STATUS_EVENTS.get(response.status_code):
            logger.warning(event, client_ip, path)
        return response


__all__ = ["RequestLoggingMiddleware"]
