import logging
import sys
import contextvars
import time
from typing import Optional, Dict, Any
from enum import Enum

# Context variable for request correlation IDs
correlation_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "correlation_id", default=None
)


class LogFormat(Enum):
    SIMPLE = "simple"
    JSON = "json"


class CorrelationFilter(logging.Filter):
    """Add correlation ID to log records."""

    def filter(self, record):
        record.correlation_id = correlation_id.get() or "none"
        return True


class JsonFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record):
        import json

        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", "none"),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


def setup_logging(
    app_name: str = "off_key",
    log_level: str = "INFO",
    log_format: LogFormat = LogFormat.SIMPLE,
    enable_correlation: bool = True,
) -> logging.Logger:
    """
    Set up centralized logging configuration.

    Args:
        app_name: Name for the logger instance
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_format: Format type (simple or json)
        enable_correlation: Whether to enable correlation ID tracking

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(app_name)
    logger.setLevel(getattr(logging, log_level.upper()))

    # Clear any existing handlers to avoid duplicates
    logger.handlers.clear()

    # Create handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, log_level.upper()))

    # Add correlation filter if enabled
    if enable_correlation:
        handler.addFilter(CorrelationFilter())

    # Set formatter based on format type
    if log_format == LogFormat.JSON:
        formatter = JsonFormatter()
    else:
        if enable_correlation:
            format_string = (
                "%(asctime)s - %(levelname)s - %(name)s "
                "- [%(correlation_id)s] - %(message)s"
            )
        else:
            format_string = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
        formatter = logging.Formatter(format_string)

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


def set_correlation_id(request_id: str) -> None:
    """Set correlation ID for current context."""
    correlation_id.set(request_id)


def get_correlation_id() -> Optional[str]:
    """Get current correlation ID."""
    return correlation_id.get()


def log_performance(
    operation: str, start_time: float, logger_instance: Optional[logging.Logger] = None
) -> None:
    """Log performance timing for operations."""
    duration = time.time() - start_time
    log_instance = logger_instance or logger
    log_instance.info(f"Performance: {operation} completed in {duration:.3f}s")


def log_security_event(
    event_type: str,
    user_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    logger_instance: Optional[logging.Logger] = None,
) -> None:
    """Log security-related events with consistent format."""
    log_instance = logger_instance or logger

    message = f"Security Event: {event_type}"
    if user_id:
        message += f" | User: {user_id}"
    if details:
        detail_str = " | ".join(f"{k}: {v}" for k, v in details.items())
        message += f" | {detail_str}"

    log_instance.warning(message)


# Default logger instance for backward compatibility
logger = setup_logging()

__all__ = [
    "logger",
    "setup_logging",
    "set_correlation_id",
    "get_correlation_id",
    "log_performance",
    "log_security_event",
    "LogFormat",
]
