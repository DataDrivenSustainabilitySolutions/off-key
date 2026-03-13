"""
RADAR Service Main Entry Point

MQTT Real-Time Anomaly Detector for Analysis and Reporting
"""

import asyncio
import logging
import sys
from pathlib import Path

from off_key_core.config.env import load_env
from off_key_core.config.validation import validate_settings
from off_key_core.config.logs import (
    load_yaml_config,
    logger,
    log_startup_logging_configuration,
)
from .service import get_radar_service
from .config.config import get_radar_settings, load_configuration
from .config.runtime import get_radar_runtime_file_settings


def setup_logging():
    """Load RADAR logging YAML and silence noisy third-party libraries."""
    service_logging_config = Path(__file__).parent / "config" / "logging.yaml"
    load_yaml_config(str(service_logging_config))
    logging.getLogger("paho.mqtt").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)


async def main():
    """Main entry point for RADAR service"""
    setup_logging()
    log_startup_logging_configuration("mqtt-radar")
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

    logger.info("event=radar.service_bootstrap_start")
    cfg = get_radar_settings().config
    logger.info(
        "event=radar.configuration_summary",
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
        logger.info("event=radar.keyboard_interrupt")
    except Exception as e:
        logger.error("event=radar.fatal_error error=%s", str(e), exc_info=True)
        sys.exit(1)

    logger.info("event=radar.service_bootstrap_stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("event=radar.service_interrupted_by_user")
    except Exception as e:
        logger.error("event=radar.service_start_failed error=%s", str(e), exc_info=True)
        sys.exit(1)
