"""
Entry point for MQTT proxy service package execution.

This module serves as the main entry point when running the MQTT service package
with `python -m off_key.services.mqtt`. It prevents RuntimeWarning issues that
occur when a module is both imported as a package component and executed as a script.
"""

import asyncio
from pathlib import Path

from off_key_core.config.logs import load_yaml_config

# Load logging configuration from YAML files
service_logging_config = Path(__file__).parent / "config" / "logging.yaml"
load_yaml_config(str(service_logging_config))

from off_key_core.clients.provider import get_charger_api_client
from .proxy import MQTTProxyService


async def main():
    """Main entry point for MQTT proxy service"""
    api_client = get_charger_api_client()
    service = MQTTProxyService(api_client)
    await service.run()


if __name__ == "__main__":
    asyncio.run(main())
