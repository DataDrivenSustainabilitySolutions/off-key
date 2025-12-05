import os
import re
import time
import yaml
import contextvars
import logging.config

from pathlib import Path
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


class TruncatingFormatter(logging.Formatter):
    """Formatter that truncates long messages for stdout."""

    def __init__(self, base_format=None, truncate_length=40):
        self.base_formatter = logging.Formatter(base_format) if base_format else None
        self.truncate_length = truncate_length

    def format(self, record):
        # Format using the base formatter if provided
        if self.base_formatter:
            formatted_msg = self.base_formatter.format(record)
        else:
            formatted_msg = super().format(record)

        # Find the message part after the last " - "
        parts = formatted_msg.split(" - ")
        if len(parts) > 1:
            # Reconstruct with truncated message
            prefix_parts = parts[:-1]
            message_part = parts[-1]

            if len(message_part) > self.truncate_length:
                message_part = message_part[: self.truncate_length] + "..."

            return " - ".join(prefix_parts + [message_part])

        return formatted_msg


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


def load_yaml_config(service_config_path: str = None) -> None:
    """
    Load logging configuration from YAML files.

    Loads the base configuration from core and optionally merges
    service-specific configuration.

    Args:
        service_config_path: Path to service-specific logging.yaml
    """
    global _default_logger_instance, _service_logger_name

    # Load base configuration from core
    core_config_path = Path(__file__).parent / "logging.yaml"

    with open(core_config_path, "r") as f:
        config_text = f.read()
        # Expand environment variables
        config_text = _expand_env_vars(config_text)
        config = yaml.safe_load(config_text)

    # Load and merge service-specific configuration if provided
    if service_config_path and os.path.exists(service_config_path):
        with open(service_config_path, "r") as f:
            service_config_text = f.read()
            # Expand environment variables
            service_config_text = _expand_env_vars(service_config_text)
            service_config = yaml.safe_load(service_config_text)

        # Extract the service logger name from the service config
        # Look for the first logger that's not sqlalchemy-related
        if "loggers" in service_config:
            logger_names = list(service_config["loggers"].keys())
            if logger_names:
                _service_logger_name = logger_names[0]

        # Merge configurations (service config overrides base)
        config = _merge_configs(config, service_config)

    # Disable the lazy logger since we're using YAML config
    _default_logger_instance = "YAML_CONFIGURED"

    # Apply the configuration
    logging.config.dictConfig(config)


def _expand_env_vars(text: str) -> str:
    """
    Expand environment variables in text using ${VAR:default} syntax.

    Examples:
        ${LOG_LEVEL:INFO} -> Uses LOG_LEVEL env var, defaults to INFO
        ${LOG_FILE:/tmp/app.log} -> Uses LOG_FILE env var, defaults to /tmp/app.log
    """

    def replace_env_var(match):
        var_expr = match.group(1)
        if ":" in var_expr:
            var_name, default_value = var_expr.split(":", 1)
        else:
            var_name = var_expr
            default_value = ""

        # Handle nested environment variable references
        result = os.getenv(var_name.strip(), default_value.strip())

        # If the result contains another ${} reference, expand it recursively
        if "${" in result:
            result = _expand_env_vars(result)

        return result

    # Match ${VAR} or ${VAR:default}
    pattern = r"\$\{([^}]+)\}"

    # Keep expanding until no more variables are found
    prev_text = None
    while prev_text != text:
        prev_text = text
        text = re.sub(pattern, replace_env_var, text)

    return text


def _merge_configs(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Merge two configuration dictionaries."""
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_configs(result[key], value)
        else:
            result[key] = value

    return result


# Global variables for YAML configuration
_default_logger_instance = None
_service_logger_name = None  # Store the service logger name when YAML is configured


class LazyLogger:
    """A lazy logger that creates the actual logger on first use."""

    def __getattr__(self, name):
        global _default_logger_instance, _service_logger_name
        if _default_logger_instance == "YAML_CONFIGURED":
            # When YAML config is used, return the service logger
            if _service_logger_name:
                return getattr(logging.getLogger(_service_logger_name), name)
            # Fallback to root logger if service name not detected
            return getattr(logging.getLogger(), name)
        else:
            # No YAML config loaded - use basic logging
            return getattr(logging.getLogger("off_key"), name)

    def __call__(self, *args, **kwargs):
        # Handle cases where logger might be called directly
        global _default_logger_instance, _service_logger_name
        if _default_logger_instance == "YAML_CONFIGURED":
            # When YAML config is used, return the service logger
            if _service_logger_name:
                return logging.getLogger(_service_logger_name)
            # Fallback to root logger if service name not detected
            return logging.getLogger()
        else:
            # No YAML config loaded - use basic logging
            return logging.getLogger("off_key")


logger = LazyLogger()


__all__ = [
    "logger",
    "load_yaml_config",
    "set_correlation_id",
    "get_correlation_id",
    "log_performance",
    "log_security_event",
    "LogFormat",
    "TruncatingFormatter",
    "CorrelationFilter",
]
