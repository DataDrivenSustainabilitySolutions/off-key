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
    "AppSettings",
    "AuthSettings",
    "DatabaseSettings",
    "EmailSettings",
    "LoggingSettings",
    "RuntimeSettings",
    "ServiceEndpointsSettings",
    "TelemetrySettings",
    "get_app_settings",
    "get_auth_settings",
    "get_database_settings",
    "get_email_settings",
    "get_logging_settings",
    "get_retention_days",
    "get_runtime_settings",
    "get_service_endpoints_settings",
    "get_telemetry_settings",
]
