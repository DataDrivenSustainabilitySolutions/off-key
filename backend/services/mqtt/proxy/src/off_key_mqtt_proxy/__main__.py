"""
Entry point for MQTT proxy service package execution.

This module serves as the main entry point when running the MQTT service package
with `python -m off_key.services.mqtt`. It prevents RuntimeWarning issues that
occur when a module is both imported as a package component and executed as a script.
"""

import asyncio
from off_key_core.clients.provider import get_charger_api_client
from off_key_core.config.env import load_env
from off_key_core.config.pionix import get_pionix_settings
from off_key_core.config.validation import validate_settings
from .config import get_mqtt_settings
from .proxy import MQTTProxyService


async def main():
    """Main entry point for MQTT proxy service"""
    load_env()
    validate_settings(
        [
            ("pionix", get_pionix_settings),
            ("mqtt_proxy", get_mqtt_settings),
        ],
        context="MQTT proxy configuration",
    )
    api_client = get_charger_api_client()
    service = MQTTProxyService(api_client)
    await service.run()


if __name__ == "__main__":
    asyncio.run(main())
