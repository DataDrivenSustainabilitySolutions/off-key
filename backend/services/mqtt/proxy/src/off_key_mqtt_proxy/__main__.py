"""
Entry point for MQTT proxy service package execution.

This module serves as the main entry point when running the MQTT service package
with `python -m off_key.services.mqtt`. It prevents RuntimeWarning issues that
occur when a module is both imported as a package component and executed as a script.
"""

import asyncio
from pathlib import Path

from .proxy import MQTTProxyService
from .health_api import run_health_api
from off_key_core.config.env import load_env
from off_key_core.config.validation import validate_settings
from off_key_core.config.logs import (
    load_yaml_config,
    logger,
    log_startup_logging_configuration,
)
from .config.config import get_mqtt_settings

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
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            if task.done():
                continue
            task.cancel()

        for task in tasks:
            if task.done():
                continue
            try:
                await task
            except asyncio.CancelledError:
                pass

        logger.info("MQTT proxy service shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
