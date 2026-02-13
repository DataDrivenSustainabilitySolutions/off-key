"""Centralized configuration helpers for off-key core."""

import logging

from .app import AppSettings, get_app_settings
from .auth import AuthSettings, get_auth_settings
from .database import DatabaseSettings, get_database_settings
from .email import EmailSettings, get_email_settings
from .logging import LoggingSettings, get_logging_settings
from .pionix import PionixConfig, PionixSettings, get_pionix_settings
from .services import (
    ServiceEndpointsSettings,
    _clear_service_endpoints_settings_cache,
    get_service_endpoints_settings,
)
from .telemetry import TelemetrySettings, get_telemetry_settings


def get_retention_days() -> int:
    """Return validated telemetry retention days for use across services."""
    return get_telemetry_settings().retention_days


def reset_runtime_caches_for_tests() -> None:
    """Clear runtime caches for deterministic tests and local tooling."""
    from .config import reset_settings_cache

    from off_key_core.clients.provider import get_charger_api_client
    from off_key_core.db.base import reset_db_runtime_caches

    reset_settings_cache()
    get_app_settings.cache_clear()
    get_auth_settings.cache_clear()
    get_database_settings.cache_clear()
    get_email_settings.cache_clear()
    get_logging_settings.cache_clear()
    get_pionix_settings.cache_clear()
    _clear_service_endpoints_settings_cache()
    get_telemetry_settings.cache_clear()
    get_charger_api_client.cache_clear()
    try:
        from off_key_core.utils.mail import reset_mail_runtime_caches
    except ImportError as exc:
        logging.getLogger(__name__).warning(
            "Skipping mail cache reset due to import error: %s", exc
        )
        reset_mail_runtime_caches = None
    if reset_mail_runtime_caches is not None:
        reset_mail_runtime_caches()
    reset_db_runtime_caches()


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
    "PionixConfig",
    "PionixSettings",
    "get_pionix_settings",
    "ServiceEndpointsSettings",
    "get_service_endpoints_settings",
    "TelemetrySettings",
    "get_telemetry_settings",
    "reset_runtime_caches_for_tests",
]
