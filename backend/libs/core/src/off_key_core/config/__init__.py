"""Centralized configuration helpers for off-key core."""

from .app import AppSettings, get_app_settings
from .auth import AuthSettings, get_auth_settings
from .database import DatabaseSettings, get_database_settings
from .email import EmailSettings, get_email_settings
from .logging import LoggingSettings, get_logging_settings
from .runtime import RuntimeSettings, get_runtime_settings
from .services import (
    ServiceEndpointsSettings,
    get_service_endpoints_settings,
)
from .telemetry import TelemetrySettings, get_telemetry_settings


def get_retention_days() -> int:
    """Return validated telemetry retention days for use across services."""
    return get_telemetry_settings().retention_days


__all__ = [
    "get_retention_days",
    "AppSettings",
    "get_app_settings",
    "AuthSettings",
    "get_auth_settings",
    "DatabaseSettings",
    "get_database_settings",
    "EmailSettings",
    "get_email_settings",
    "LoggingSettings",
    "get_logging_settings",
    "RuntimeSettings",
    "get_runtime_settings",
    "ServiceEndpointsSettings",
    "get_service_endpoints_settings",
    "TelemetrySettings",
    "get_telemetry_settings",
]
