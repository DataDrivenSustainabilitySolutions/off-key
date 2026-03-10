"""Test-only runtime cache reset helpers.

This module intentionally lives under ``tests`` so cache reset orchestration
does not become part of the production ``off_key_core.config`` API.
"""

import logging

from off_key_core.clients.provider import get_charger_api_client
from off_key_core.config.app import get_app_settings
from off_key_core.config.auth import get_auth_settings
from off_key_core.config.database import get_database_settings
from off_key_core.config.email import get_email_settings
from off_key_core.config.logging import get_logging_settings
from off_key_core.config.pionix import get_pionix_settings
from off_key_core.config.runtime import get_runtime_settings
from off_key_core.config.services import _clear_service_endpoints_settings_cache
from off_key_core.config.telemetry import get_telemetry_settings
from off_key_core.db.base import reset_db_runtime_caches


def reset_runtime_caches_for_tests() -> None:
    """Clear runtime caches for deterministic tests and local test tooling."""
    get_app_settings.cache_clear()
    get_auth_settings.cache_clear()
    get_database_settings.cache_clear()
    get_email_settings.cache_clear()
    get_logging_settings.cache_clear()
    get_pionix_settings.cache_clear()
    get_runtime_settings.cache_clear()
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
