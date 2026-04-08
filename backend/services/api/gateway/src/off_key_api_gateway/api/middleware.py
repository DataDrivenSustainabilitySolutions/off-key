import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from off_key_core.config.logging import get_logging_settings
from off_key_core.config.logs import (
    set_correlation_id,
    log_performance,
    logger,
    redact_ip_address,
    redact_query_params,
)


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for request/response logging and correlation ID tracking."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        settings = get_logging_settings()
        start_time = time.time()

        # Generate or extract correlation ID
        correlation_id = request.headers.get(settings.LOG_CORRELATION_HEADER) or str(
            uuid.uuid4()
        )
        set_correlation_id(correlation_id)
        method = request.method
        path = request.url.path
        user_agent = request.headers.get("user-agent", "unknown")
        safe_user_agent = (
            user_agent if len(user_agent) <= 120 else f"{user_agent[:117]}..."
        )
        safe_query = redact_query_params(dict(request.query_params))

        try:
            # Process request
            response = await call_next(request)
            duration_ms = (time.time() - start_time) * 1000

            # Log performance
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

        # Add correlation ID to response headers
        response.headers[settings.LOG_CORRELATION_HEADER] = correlation_id

        return response


class SecurityLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for security event logging."""

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Log potential security events
        client_ip = redact_ip_address(request.client.host if request.client else None)
        path = request.url.path
        user_agent = request.headers.get("user-agent", "unknown")
        safe_user_agent = (
            user_agent if len(user_agent) <= 120 else f"{user_agent[:117]}..."
        )

        # Log suspicious patterns
        if self._is_suspicious_request(request):
            logger.warning(
                "event=security.suspicious_request ip=%s method=%s "
                "path=%s user_agent=%s",
                client_ip,
                request.method,
                path,
                safe_user_agent,
            )

        response = await call_next(request)

        # Log authentication failures
        if response.status_code == 401:
            logger.warning(
                "event=security.authentication_failed ip=%s path=%s",
                client_ip,
                path,
            )

        # Log authorization failures
        if response.status_code == 403:
            logger.warning(
                "event=security.authorization_failed ip=%s path=%s",
                client_ip,
                path,
            )

        return response

    def _is_suspicious_request(self, request: Request) -> bool:
        """Detect potentially suspicious request patterns."""
        path = request.url.path.lower()

        # Common attack patterns
        suspicious_patterns = [
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
        ]

        return any(pattern in path for pattern in suspicious_patterns)


__all__ = ["LoggingMiddleware", "SecurityLoggingMiddleware"]
