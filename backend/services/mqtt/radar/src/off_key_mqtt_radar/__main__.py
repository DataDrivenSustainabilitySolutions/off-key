"""
RADAR Service Main Entry Point

MQTT Real-Time Anomaly Detector for Analysis and Reporting
"""

import asyncio
import sys
from pathlib import Path

from off_key_core.config.bootstrap import start_service
from off_key_core.config.logs import logger

from .config.config import get_radar_settings, load_configuration
from .config.runtime import get_radar_runtime_file_settings
from .service import get_radar_service


async def main():
    """Main entry point for RADAR service"""
    # The optional config file loads before logging, so it may set log levels.
    config_file = start_service(
        "mqtt-radar",
        Path(__file__).parent / "config" / "logging.yaml",
        [("radar", lambda: get_radar_settings().config)],
        context="RADAR service configuration",
        after_env=lambda: load_configuration(
            get_radar_runtime_file_settings().RADAR_CONFIG_FILE
        ),
    )
    if config_file:
        logger.info(
            "event=radar.config_file_loaded path=%s changes_require_restart=true",
            config_file,
        )

    logger.info("event=radar.service_bootstrap_start")
    cfg = get_radar_settings().config
    logger.info(
        "event=radar.configuration_summary",
        extra={
            "broker": f"{cfg.broker_host}:{cfg.broker_port}",
            "topics": cfg.subscription_topics,
            "model_type": cfg.monitoring.model_type,
            "db_write_enabled": cfg.db_write_enabled,
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
