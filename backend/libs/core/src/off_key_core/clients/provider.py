"""
Legacy charger API provider hooks.

The runtime API-provider integration was removed as part of the MQTT-first
ingestion cutover.
"""

from functools import lru_cache
from typing import Optional

from off_key_core.clients.base_client import ChargerAPIClient


class ChargerAPIProviderRemovedError(RuntimeError):
    """Raised when deprecated API-provider access is requested."""


_REMOVAL_MESSAGE = (
    "Charger API providers were removed in MQTT-first mode. "
    "Use MQTT topic subscriptions instead."
)


@lru_cache()
def get_charger_api_client() -> ChargerAPIClient:
    """Deprecated provider entrypoint retained for compatibility."""
    raise ChargerAPIProviderRemovedError(_REMOVAL_MESSAGE)


def get_charger_api_client_factory(provider: Optional[str] = None) -> ChargerAPIClient:
    """Deprecated factory retained for compatibility."""
    raise ChargerAPIProviderRemovedError(_REMOVAL_MESSAGE)
