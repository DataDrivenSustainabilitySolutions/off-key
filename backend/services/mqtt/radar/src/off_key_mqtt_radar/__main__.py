"""
RADAR Service Main Entry Point

MQTT Real-Time Anomaly Detector for Analysis and Reporting
"""

import asyncio
import logging
import sys

from off_key_core.config.logs import logger
from .service import get_radar_service
from .config import radar_settings


def setup_logging():
    """Setup logging configuration"""
    log_level = getattr(radar_settings, "RADAR_LOG_LEVEL", "INFO")

    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )

    # Set specific logger levels
    logging.getLogger("paho.mqtt").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)


async def main():
    """Main entry point for RADAR service"""
    setup_logging()

    logger.info("Starting MQTT RADAR service")
    logger.info(f"Configuration: {radar_settings.config.model_dump()}")

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
