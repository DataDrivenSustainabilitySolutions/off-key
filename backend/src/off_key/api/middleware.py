import time
import uuid
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from ..core.logs import set_correlation_id, log_performance, logger
from ..core.config import settings


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for request/response logging and correlation ID tracking."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()

        # Generate or extract correlation ID
        correlation_id = request.headers.get(settings.LOG_CORRELATION_HEADER) or str(
            uuid.uuid4()
        )
        set_correlation_id(correlation_id)

        # Log incoming request
        if settings.ENABLE_REQUEST_LOGGING:
            logger.info(
                f"Request: {request.method} {request.url.path} | "
                f"Query: {dict(request.query_params)} | "
                f"User-Agent: {request.headers.get('user-agent', 'unknown')}"
            )

        try:
            # Process request
            response = await call_next(request)

            # Log response
            if settings.ENABLE_REQUEST_LOGGING:
                logger.info(
                    f"Response: {response.status_code} | "
                    f"Content-Type: {response.headers.get('content-type', 'unknown')}"
                )

            # Log performance
            if settings.ENABLE_PERFORMANCE_LOGGING:
                log_performance(f"{request.method} {request.url.path}", start_time)

        except Exception as e:
            # Log errors with correlation context
            logger.error(
                f"Request failed: {request.method} {request.url.path} | "
                f"Error: {str(e)}"
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
        client_ip = request.client.host if request.client else "unknown"

        # Log suspicious patterns
        if self._is_suspicious_request(request):
            logger.warning(
                f"Suspicious request detected | "
                f"IP: {client_ip} | "
                f"Method: {request.method} | "
                f"Path: {request.url.path} | "
                f"User-Agent: {request.headers.get('user-agent', 'unknown')}"
            )

        response = await call_next(request)

        # Log authentication failures
        if response.status_code == 401:
            logger.warning(
                f"Authentication failed | "
                f"IP: {client_ip} | "
                f"Path: {request.url.path}"
            )

        # Log authorization failures
        if response.status_code == 403:
            logger.warning(
                f"Authorization failed | "
                f"IP: {client_ip} | "
                f"Path: {request.url.path}"
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
