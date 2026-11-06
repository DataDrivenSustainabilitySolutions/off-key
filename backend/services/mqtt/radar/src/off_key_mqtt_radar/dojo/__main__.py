"""Dojo worker entry point: ``python -m off_key_mqtt_radar.dojo``."""

import asyncio
import signal
from pathlib import Path

from off_key_core.config.bootstrap import start_service
from sqlalchemy.ext.asyncio import create_async_engine

from ..config.runtime import get_radar_database_settings
from .settings import DojoWorkerSettings
from .worker import DojoWorker


async def main() -> None:
    start_service(
        "dojo-worker",
        Path(__file__).parent / "logging.yaml",
        [
            ("dojo", DojoWorkerSettings),
            ("database", get_radar_database_settings),
        ],
        context="Dojo worker configuration",
    )
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    # Replays run on this thread between awaits, so a plain flag the replay
    # loop polls is the reliable way to stop between two points.
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    engine = create_async_engine(
        get_radar_database_settings().async_database_url, pool_pre_ping=True
    )
    try:
        await DojoWorker(
            engine, DojoWorkerSettings().options(), lambda: stopping
        ).run_forever()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
