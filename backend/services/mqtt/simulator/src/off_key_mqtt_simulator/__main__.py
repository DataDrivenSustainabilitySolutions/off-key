"""MQTT simulator service entrypoint."""

import asyncio
import signal

from off_key_core.config.bootstrap import start_service
from off_key_core.config.logs import logger

from .config import get_simulator_settings
from .service import SimulatorService


async def main() -> None:
    start_service(
        "mqtt-simulator",
        None,
        [("mqtt_simulator", lambda: get_simulator_settings().config)],
        context="MQTT simulator configuration",
    )
    config = get_simulator_settings().config
    if not config.enabled:
        logger.info("MQTT simulator disabled by configuration")
        return

    service = SimulatorService(config)

    def _signal_handler(signum, frame):
        logger.info("Received signal %s, stopping MQTT simulator", signum)
        service.request_shutdown()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    await service.run()


if __name__ == "__main__":
    asyncio.run(main())
