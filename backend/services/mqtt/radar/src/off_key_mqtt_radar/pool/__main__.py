"""RADAR pool entry point: ``python -m off_key_mqtt_radar.pool``."""

import asyncio
import signal
from pathlib import Path

from off_key_core.config.bootstrap import start_service
from sqlalchemy.ext.asyncio import create_async_engine

from ..config.runtime import get_radar_database_settings
from .settings import RadarPoolSettings
from .worker import RadarPool


async def serve_health(pool: RadarPool, port: int) -> asyncio.Server:
    """Answer any request: 200 while the last poll reached the database, else 503."""

    async def answer(reader, writer):
        try:
            await asyncio.wait_for(reader.readline(), 5)
            status = "200 OK" if pool.healthy else "503 Service Unavailable"
            body = b'{"status":"%s"}' % (b"ok" if pool.healthy else b"unavailable")
            writer.write(
                f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                + body
            )
            await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    return await asyncio.start_server(answer, "0.0.0.0", port)


async def main() -> None:
    start_service(
        "radar-pool",
        Path(__file__).parent / "logging.yaml",
        [
            ("pool", RadarPoolSettings),
            ("database", get_radar_database_settings),
        ],
        context="RADAR pool configuration",
    )
    settings = RadarPoolSettings()
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopping.set)
    engine = create_async_engine(
        get_radar_database_settings().async_database_url,
        pool_size=2,
        max_overflow=0,
        pool_pre_ping=True,
        hide_parameters=True,
    )
    pool = RadarPool(engine, settings.options(), stopping.is_set)
    server = await serve_health(pool, settings.RADAR_POOL_HEALTH_PORT)
    try:
        await pool.run_forever()
    finally:
        server.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
