"""
RADAR Service Main Entry Point

MQTT Real-Time Anomaly Detector for Analysis and Reporting
"""

import asyncio
import sys
from pathlib import Path

from off_key_core.config.logs import load_yaml_config, logger
from .service import get_radar_service
from .config.config import radar_settings

# Load logging configuration from YAML files
service_logging_config = Path(__file__).parent / "config" / "logging.yaml"
load_yaml_config(str(service_logging_config))


async def main():
    """Main entry point for RADAR service"""
    logger.info("Starting MQTT RADAR service")
    logger.info(f"Configuration: {radar_settings.config.dict()}")

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
