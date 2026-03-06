"""
RADAR Service Main Entry Point

MQTT Real-Time Anomaly Detector for Analysis and Reporting
"""

import asyncio
import logging
import sys

from off_key_core.config.env import load_env
from off_key_core.config.validation import validate_settings
from off_key_core.config.logs import logger
from .service import get_radar_service
from .config.config import get_radar_settings, load_configuration
from .config.runtime import get_radar_runtime_file_settings


def setup_logging():
    """Configure logging levels for third-party libraries.

    The main application logger is already configured by off_key_core.config.logs
    at import time. This function only silences noisy third-party loggers.
    """
    logging.getLogger("paho.mqtt").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)


async def main():
    """Main entry point for RADAR service"""
    setup_logging()
    load_env()
    runtime_file_settings = get_radar_runtime_file_settings()
    settings = get_radar_settings()
    settings.custom_config_file = load_configuration(
        runtime_file_settings.RADAR_CONFIG_FILE
    )
    validate_settings(
        [("radar", lambda: get_radar_settings().config)],
        context="RADAR service configuration",
    )

    logger.info("Starting MQTT RADAR service")
    cfg = get_radar_settings().config
    logger.info(
        "Configuration summary",
        extra={
            "broker": f"{cfg.broker_host}:{cfg.broker_port}",
            "topics": cfg.subscription_topics,
            "model_type": cfg.model_type,
            "db_write_enabled": cfg.db_write_enabled,
            "batch_size": cfg.batch_size,
            "log_level": cfg.log_level,
        },
    )

    try:
        # Get service instance and run
        radar_service = get_radar_service()
        await radar_service.run()

    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Fatal error in RADAR service: {e}", exc_info=True)
        sys.exit(1)

    logger.info("MQTT RADAR service stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Service interrupted by user")
    except Exception as e:
        logger.error(f"Failed to start service: {e}", exc_info=True)
        sys.exit(1)
