import os
import re
import time
import yaml
import contextvars
import hashlib
import ipaddress
import logging
import logging.config

from pathlib import Path
from typing import Optional, Dict, Any, Mapping
from enum import Enum

from .logging import get_logging_settings

# Context variable for request correlation IDs
correlation_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "correlation_id", default=None
)

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|token|secret|api[_-]?key|authorization|cookie|session|email|user|ip)",
    re.IGNORECASE,
)
_STANDARD_RECORD_FIELDS = set(logging.makeLogRecord({}).__dict__.keys())


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

        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_RECORD_FIELDS and not key.startswith("_")
        }
        if extra:
            log_data["extra"] = redact_query_params(extra, level=record.levelno)

        return json.dumps(log_data, default=str)


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


def _should_redact(level: int = logging.INFO) -> bool:
    settings = get_logging_settings()
    if not settings.LOG_REDACT_PII:
        return False
    if settings.LOG_PII_DEBUG_UNMASK and level <= logging.DEBUG:
        return False
    return True


def _is_sensitive_key(key: str) -> bool:
    return bool(_SENSITIVE_KEY_PATTERN.search(key))


def _mask_text(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 2:
        return "*" * len(value)
    return f"{value[0]}***{value[-1]}"


def _hash_token(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    return f"sha256:{digest}"


def redact_email(email: str, *, level: int = logging.INFO) -> str:
    """Mask email-like identifiers for logs."""
    if not _should_redact(level):
        return email
    if "@" not in email:
        return _mask_text(email)
    local, domain = email.split("@", 1)
    domain_head = domain.split(".", 1)[0]
    suffix = ""
    if "." in domain:
        _, suffix = domain.split(".", 1)
        suffix = f".{suffix}"
    return f"{_mask_text(local)}@{_mask_text(domain_head)}{suffix}"


def redact_ip_address(ip_value: Optional[str], *, level: int = logging.INFO) -> str:
    """Mask IP addresses for logs."""
    if not ip_value:
        return "unknown"
    if not _should_redact(level):
        return ip_value
    try:
        ip_obj = ipaddress.ip_address(ip_value)
    except ValueError:
        return _mask_text(ip_value)

    if isinstance(ip_obj, ipaddress.IPv4Address):
        octets = ip_obj.exploded.split(".")
        return ".".join(octets[:3] + ["x"])

    groups = ip_obj.exploded.split(":")
    return ":".join(groups[:4] + ["x", "x", "x", "x"])


def redact_value(value: Any, *, level: int = logging.INFO) -> Any:
    """Redact sensitive value content for log output."""
    if value is None:
        return None
    if not _should_redact(level):
        return value

    if isinstance(value, str):
        lowered = value.lower()
        if "@" in value:
            return redact_email(value, level=level)
        if len(value) > 12 and any(
            token in lowered for token in ("token", "bearer", "secret", "apikey", "api")
        ):
            return _hash_token(value)
        return _mask_text(value)

    if isinstance(value, (int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return redact_query_params(value, level=level)

    return _mask_text(str(value))


def redact_query_params(
    params: Mapping[str, Any], *, level: int = logging.INFO
) -> Dict[str, Any]:
    """Return query params with sensitive keys masked."""
    redacted: Dict[str, Any] = {}
    for key, value in params.items():
        if _is_sensitive_key(str(key)):
            redacted[key] = redact_value(value, level=level)
            continue
        if isinstance(value, str) and len(value) > 120:
            redacted[key] = f"{value[:117]}..."
            continue
        redacted[key] = value
    return redacted


def log_performance(
    operation: str,
    start_time: float,
    logger_instance: Optional[logging.Logger] = None,
    slow_threshold_seconds: float = 1.0,
) -> None:
    """Log performance timing for operations."""
    duration = time.time() - start_time
    log_instance = logger_instance or logger
    if duration >= slow_threshold_seconds:
        log_instance.warning(
            "event=performance operation=%s duration_s=%.3f threshold_s=%.3f",
            operation,
            duration,
            slow_threshold_seconds,
        )
        return
    log_instance.debug(
        "event=performance operation=%s duration_s=%.3f", operation, duration
    )


def log_security_event(
    event_type: str,
    user_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    logger_instance: Optional[logging.Logger] = None,
    level: Optional[int] = None,
) -> None:
    """Log security-related events with consistent format."""
    log_instance = logger_instance or logger
    resolved_level = level or _infer_security_level(event_type)

    redacted_details = {
        key: (
            redact_value(value, level=resolved_level)
            if _is_sensitive_key(key)
            else value
        )
        for key, value in (details or {}).items()
    }
    redacted_user_id = (
        redact_email(user_id, level=resolved_level)
        if isinstance(user_id, str) and "@" in user_id
        else redact_value(user_id, level=resolved_level)
    )
    details_repr = redacted_details if redacted_details else {}

    log_instance.log(
        resolved_level,
        "event=security.%s user=%s details=%s",
        event_type,
        redacted_user_id or "none",
        details_repr,
    )


def _infer_security_level(event_type: str) -> int:
    token = event_type.strip().lower()
    if any(word in token for word in ("breach", "critical", "compromised")):
        return logging.ERROR
    if any(
        word in token
        for word in (
            "fail",
            "denied",
            "forbidden",
            "invalid",
            "unauthorized",
            "suspicious",
            "error",
        )
    ):
        return logging.WARNING
    return logging.INFO


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

    _apply_log_format(config)
    _ensure_root_handlers(config)

    # Disable the lazy logger since we're using YAML config
    _default_logger_instance = "YAML_CONFIGURED"

    # Apply the configuration
    logging.config.dictConfig(config)


def _apply_log_format(config: Dict[str, Any]) -> None:
    """Apply LOG_FORMAT override to handler formatter choices."""
    selected = os.getenv("LOG_FORMAT", LogFormat.SIMPLE.value).strip().lower()
    handlers = config.get("handlers", {})

    if selected == LogFormat.JSON.value:
        for handler in handlers.values():
            handler["formatter"] = "json"
        return

    for name, handler in handlers.items():
        if name == "console_truncated":
            handler["formatter"] = "truncated"
            continue
        handler["formatter"] = "detailed"


def _ensure_root_handlers(config: Dict[str, Any]) -> None:
    """Ensure root logger has a fallback handler for unknown logger names."""
    root_logger = config.setdefault("root", {})
    handlers = root_logger.get("handlers")
    if not handlers:
        root_logger["handlers"] = ["console"]


def log_startup_logging_configuration(
    service_name: str,
    logger_name: Optional[str] = None,
    logger_instance: Optional[logging.Logger] = None,
) -> None:
    """Emit one startup log describing effective logger wiring."""
    log_instance = logger_instance or logger
    settings = get_logging_settings()
    effective_name = logger_name or _service_logger_name or "root"
    target_logger = (
        logging.getLogger()
        if effective_name == "root"
        else logging.getLogger(effective_name)
    )
    handler_names = [handler.__class__.__name__ for handler in target_logger.handlers]
    root_handler_names = [
        handler.__class__.__name__ for handler in logging.getLogger().handlers
    ]

    log_instance.info(
        "event=logging_configured service=%s logger=%s level=%s "
        "format=%s handlers=%s root_handlers=%s",
        service_name,
        effective_name,
        logging.getLevelName(target_logger.level),
        settings.LOG_FORMAT,
        handler_names,
        root_handler_names,
    )


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

        return os.getenv(var_name.strip(), default_value.strip())

    # Match only innermost ${VAR} or ${VAR:default} expressions.
    # This enables reliable nested fallback expansion like:
    # ${A:${B:${C:INFO}}}
    pattern = r"\$\{([^${}]*)\}"

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
    "redact_email",
    "redact_ip_address",
    "redact_query_params",
    "redact_value",
    "log_performance",
    "log_security_event",
    "log_startup_logging_configuration",
    "LogFormat",
    "TruncatingFormatter",
    "CorrelationFilter",
]
