from functools import lru_cache
from typing import Optional

from off_key_core.clients.base_client import ChargerAPIClient
from off_key_core.clients.pionix import PionixClient
from off_key_core.config.config import get_settings

settings = get_settings()


@lru_cache()
def get_charger_api_client() -> ChargerAPIClient:
    """
    Dependency provider for charger API client.

    Returns the appropriate client implementation based on configuration.
    The client is cached using lru_cache to ensure we reuse the same instance.

    Returns:
        ChargerAPIClient implementation based on CHARGER_API_PROVIDER setting

    Raises:
        ValueError: If the configured provider is unknown
    """
    provider = getattr(settings, "CHARGER_API_PROVIDER", "pionix")  # Default to pionix

    if provider == "pionix":
        return PionixClient(config=settings.pionix_config)
    # Future providers can be added here:
    # elif provider == "fictional":
    #     from .client.fictional import FictionalClient
    #     return FictionalClient(config=settings.fictional_config)
    else:
        raise ValueError(
            f"Unknown charger API provider: {provider}. Valid options are: 'pionix'"
        )


def get_charger_api_client_factory(provider: Optional[str] = None) -> ChargerAPIClient:
    """
    Factory function for creating charger API clients.

    This is useful for cases where you need to override the default provider,
    such as in testing or when using multiple providers simultaneously.

    Args:
        provider: Optional provider name to override the default

    Returns:
        ChargerAPIClient implementation for the specified provider
    """
    if provider is None:
        return get_charger_api_client()

    if provider == "pionix":
        return PionixClient(config=settings.pionix_config)
    # Future providers can be added here
    else:
        raise ValueError(f"Unknown charger API provider: {provider}")
