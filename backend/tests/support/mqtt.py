"""Loopback MQTT brokers and polling helpers for real RADAR integration tests."""

import asyncio
from contextlib import asynccontextmanager

from amqtt.broker import Broker
from off_key_core.schemas.radar import AdaptiveStreamConfig

ANONYMOUS_ACCESS = {
    "amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}
}


async def start_mqtt_broker(*, plugins=None, port=0) -> tuple[Broker, int]:
    """Start an in-process broker on loopback and return it with its bound port."""
    broker = Broker(
        {
            "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}},
            "plugins": plugins or ANONYMOUS_ACCESS,
        }
    )
    await broker.start()
    return broker, broker._servers["default"].instance.sockets[0].getsockname()[1]


@asynccontextmanager
async def mqtt_broker(*, plugins=None, port=0):
    broker, port = await start_mqtt_broker(plugins=plugins, port=port)
    try:
        yield broker, port
    finally:
        await broker.shutdown()


async def wait_until(predicate, deadline_seconds=20):
    async with asyncio.timeout(deadline_seconds):
        # Broker, Paho thread and database state do not expose asyncio events.
        while not predicate():  # noqa: ASYNC110
            await asyncio.sleep(0.01)


def tiny_adaptive_monitoring() -> AdaptiveStreamConfig:
    """Adaptive detector that trains and calibrates within a handful of inputs."""
    return AdaptiveStreamConfig(
        model_type="aberrant_knn",
        model_params={"k": 1, "window_size": 8, "warm_up": 1},
        training_window_size=2,
        calibration_window_size=3,
    )
