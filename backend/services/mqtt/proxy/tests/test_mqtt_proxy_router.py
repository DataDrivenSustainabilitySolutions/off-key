import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from off_key_mqtt_proxy.client.models import MQTTMessage
from off_key_mqtt_proxy.router import MessageDestination, MessageRouter


def _config():
    config = MagicMock()
    config.worker_threads = 1
    config.cleanup_interval = 60.0
    config.metrics_interval = 60.0
    config.graceful_shutdown_timeout = 5.0
    config.get_jittered_backoff_delay.return_value = 0.0
    return config


def _message() -> MQTTMessage:
    return MQTTMessage(
        topic="charger/charger-1/live-telemetry/sine",
        payload={"value": 1.0},
        timestamp=datetime.now(timezone.utc),
        qos=0,
        retain=False,
    )


class SlowDestination(MessageDestination):
    def __init__(self, release: asyncio.Event):
        super().__init__("slow")
        self.release = release

    async def process_message(self, message: MQTTMessage) -> bool:
        await self.release.wait()
        return True


@pytest.mark.asyncio
async def test_route_message_uses_unique_ids_for_fast_successive_messages():
    router = MessageRouter(config=_config())

    first = await router.route_message(_message(), destinations=[])
    second = await router.route_message(_message(), destinations=[])

    assert first.message_id != second.message_id


@pytest.mark.asyncio
async def test_route_message_clears_stale_completion_event_while_active():
    router = MessageRouter(config=_config())
    release = asyncio.Event()
    router.add_destination(SlowDestination(release))
    router._all_routes_completed_event.set()

    route_task = asyncio.create_task(router.route_message(_message(), ["slow"]))
    while not router.active_routes:
        await asyncio.sleep(0)

    assert not router._all_routes_completed_event.is_set()

    release.set()
    await route_task
    assert router._all_routes_completed_event.is_set()
