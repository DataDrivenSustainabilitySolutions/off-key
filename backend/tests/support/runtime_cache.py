"""Test-only runtime cache reset helpers.

This module intentionally lives under ``tests`` so cache reset orchestration
does not become part of the production ``aberration_core.config`` API.
"""

from aberration_api_gateway.settings import (
    get_app_settings,
    get_service_endpoints_settings,
)
from aberration_core.config.auth import get_auth_settings
from aberration_core.config.database import get_database_settings
from aberration_core.config.email import get_email_settings
from aberration_core.config.logging import get_logging_settings
from aberration_core.config.runtime import get_runtime_settings
from aberration_core.config.service_auth import get_service_auth_settings
from aberration_core.config.telemetry import get_telemetry_settings
from aberration_core.db.base import reset_db_runtime_caches
from aberration_db_sync.config.config import get_sync_settings
from aberration_mqtt_proxy.config.config import get_mqtt_settings
from aberration_mqtt_radar.config.config import get_radar_settings
from aberration_mqtt_radar.config.runtime import clear_radar_runtime_settings_cache
from aberration_tactic_middleware.config.config import clear_tactic_settings_caches
from aberration_tactic_middleware.config.system_live import get_system_live_settings

# Every cached settings getter, so a test reads the environment it set up.
SETTINGS_GETTERS = (
    get_app_settings,
    get_auth_settings,
    get_service_auth_settings,
    get_database_settings,
    get_email_settings,
    get_logging_settings,
    get_runtime_settings,
    get_service_endpoints_settings,
    get_telemetry_settings,
    get_system_live_settings,
    get_radar_settings,
    get_mqtt_settings,
    get_sync_settings,
)


def reset_settings_caches() -> None:
    """Forget every cached settings object."""
    for getter in SETTINGS_GETTERS:
        getter.cache_clear()
    clear_tactic_settings_caches()
    clear_radar_runtime_settings_cache()


def reset_runtime_caches_for_tests() -> None:
    """Clear runtime caches for deterministic tests and local test tooling."""
    reset_settings_caches()

    # The test environment installs core's mail extra with every service.
    from aberration_core.utils.mail import reset_mail_runtime_caches

    reset_mail_runtime_caches()

    reset_db_runtime_caches()
