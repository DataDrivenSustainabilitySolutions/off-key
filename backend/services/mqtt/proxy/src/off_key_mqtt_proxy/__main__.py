"""Entry point for `python -m off_key_mqtt_proxy`."""

import asyncio
from pathlib import Path

from off_key_core.config.env import load_env
from off_key_core.config.logs import (
    load_yaml_config,
    log_startup_logging_configuration,
    logger,
)
from off_key_core.config.validation import validate_settings
from off_key_core.utils.tasks import run_until_first_exit

from .config.config import get_mqtt_settings
from .health_api import run_health_api
from .proxy import MQTTProxyService

# Load logging configuration from YAML files
service_logging_config = Path(__file__).parent / "config" / "logging.yaml"
load_yaml_config(str(service_logging_config))


async def main():
    """Main entry point for MQTT proxy service"""
    load_env()
    log_startup_logging_configuration("mqtt-proxy")
    validate_settings(
        [
            ("mqtt_proxy", lambda: get_mqtt_settings().config),
        ],
        context="MQTT proxy configuration",
    )
    service = MQTTProxyService()
    settings = get_mqtt_settings()

    service_task = asyncio.create_task(
        service.run(),
        name="off-key-mqtt-proxy-service",
    )
    tasks = {service_task}

    if settings.MQTT_HEALTH_API_ENABLED:
        health_task = asyncio.create_task(
            run_health_api(service),
            name="off-key-mqtt-proxy-health-api",
        )
        tasks.add(health_task)

    try:
        await run_until_first_exit(tasks)
    finally:
        logger.info("MQTT proxy service shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
