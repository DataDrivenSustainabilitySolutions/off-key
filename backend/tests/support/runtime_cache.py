"""Test-only runtime cache reset helpers.

This module intentionally lives under ``tests`` so cache reset orchestration
does not become part of the production ``off_key_core.config`` API.
"""

from off_key_api_gateway.settings import (
    get_app_settings,
    get_service_endpoints_settings,
)
from off_key_core.config.auth import get_auth_settings
from off_key_core.config.database import get_database_settings
from off_key_core.config.email import get_email_settings
from off_key_core.config.logging import get_logging_settings
from off_key_core.config.runtime import get_runtime_settings
from off_key_core.config.service_auth import get_service_auth_settings
from off_key_core.config.telemetry import get_telemetry_settings
from off_key_core.db.base import reset_db_runtime_caches
from off_key_db_sync.config.config import get_sync_settings
from off_key_mqtt_proxy.config.config import get_mqtt_settings
from off_key_mqtt_radar.config.config import get_radar_settings
from off_key_mqtt_radar.config.runtime import clear_radar_runtime_settings_cache
from off_key_mqtt_simulator.config import get_simulator_settings
from off_key_tactic_middleware.config.collection import get_ambibox_settings
from off_key_tactic_middleware.config.config import clear_tactic_settings_caches
from off_key_tactic_middleware.config.system_live import get_system_live_settings

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
    get_ambibox_settings,
    get_system_live_settings,
    get_radar_settings,
    get_mqtt_settings,
    get_sync_settings,
    get_simulator_settings,
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
    from off_key_core.utils.mail import reset_mail_runtime_caches

    reset_mail_runtime_caches()

    reset_db_runtime_caches()
