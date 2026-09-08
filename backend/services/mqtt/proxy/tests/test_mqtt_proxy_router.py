import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from off_key_core.utils.enum import HealthStatus
from off_key_mqtt_proxy.client.models import MQTTMessage
from off_key_mqtt_proxy.destinations import MessageDestination
from off_key_mqtt_proxy.router import MessageRouter


def _config():
    config = MagicMock()
    config.worker_threads = 1
    config.metrics_interval = 60.0
    config.graceful_shutdown_timeout = 5.0
    config.get_jittered_backoff_delay.return_value = 0.0
    return config


def _message() -> MQTTMessage:
    return MQTTMessage(
        topic="device/evCharger/charger-1/sine",
        payload={"value": 1.0},
        timestamp=datetime.now(UTC),
        qos=0,
        retain=False,
    )


class SlowDestination(MessageDestination):
    def __init__(self, release: asyncio.Event):
        super().__init__("slow")
        self.release = release
        self.finished = asyncio.Event()

    async def process_message(self, message: MQTTMessage) -> bool:
        try:
            await self.release.wait()
            return True
        finally:
            self.finished.set()


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
    for _ in range(1000):
        if router.active_routes:
            break
        if route_task.done():
            await route_task
            pytest.fail("route_message completed before active_routes was populated")
        await asyncio.sleep(0.0001)
    else:
        pytest.fail("active_routes was not populated before the wait limit")

    assert not router._all_routes_completed_event.is_set()

    release.set()
    await route_task
    assert router._all_routes_completed_event.is_set()


def test_idle_destination_is_healthy_during_bootstrap():
    router = MessageRouter(config=_config())
    destination = SlowDestination(asyncio.Event())
    router.add_destination(destination)

    assert destination.get_health_status().status is HealthStatus.HEALTHY
    assert router.get_health_status().status is HealthStatus.HEALTHY


@pytest.mark.asyncio
async def test_cancelled_route_releases_active_route_tracking():
    router = MessageRouter(config=_config())
    router.add_destination(SlowDestination(asyncio.Event()))

    route_task = asyncio.create_task(router.route_message(_message(), ["slow"]))
    for _ in range(1000):
        if router.active_routes:
            break
        await asyncio.sleep(0.0001)
    else:
        pytest.fail("active route was not registered before the wait limit")

    route_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await route_task

    assert router.active_routes == {}
    assert router._all_routes_completed_event.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_route", [False, True])
async def test_database_backpressure_survives_network_deadline(cancel_route):
    from off_key_core.utils.mqtt_topics import TopicMetadataExtractor
    from off_key_mqtt_proxy.destinations import DatabaseDestination
    from off_key_mqtt_proxy.routing_models import RouteStatus
    from off_key_mqtt_proxy.telemetry import DatabaseWriter

    config = _config()
    config.batch_size = 1
    config.batch_timeout = 0.01
    config.health_monitor_interval = 60.0
    writer = DatabaseWriter(
        config, session_factory=MagicMock(), topic_extractor=TopicMetadataExtractor()
    )
    entered, release = asyncio.Event(), asyncio.Event()
    persisted = []

    async def persist(batch):
        entered.set()
        await release.wait()
        persisted.extend(record.value for record in batch.records)
        return True

    writer._process_batch = persist
    router = MessageRouter(config, TopicMetadataExtractor())
    router.route_timeout = 0.02
    router.add_destination(DatabaseDestination(writer))
    slow = SlowDestination(asyncio.Event())
    router.add_destination(slow)

    def message(value):
        result = _message()
        result.payload = {"value": value, "timestamp": result.timestamp.isoformat()}
        return result

    await writer.start()
    route = None
    try:
        await router.route_message(message(1), ["database"])
        await asyncio.wait_for(entered.wait(), 1)
        await router.route_message(message(2), ["database"])
        route = asyncio.create_task(
            router.route_message(message(3), ["database", "slow"])
        )
        # The network destination must time out while database admission waits.
        await asyncio.wait_for(slow.finished.wait(), 1)
        assert not route.done()
        [info] = list(router.active_routes.values())
        assert info.results["slow"].status is RouteStatus.TIMEOUT
        assert "database" not in info.results
        assert writer.pending_batch.size() == 1
        assert len(writer.processing_batches) == 1
        assert writer.total_records_received == 2

        if cancel_route:
            route.cancel()
            with pytest.raises(asyncio.CancelledError):
                await route
        else:
            release.set()
            result = await asyncio.wait_for(route, 1)
            assert result.results["database"].status is RouteStatus.SUCCESS
        assert not router.active_routes
        assert router._all_routes_completed_event.is_set()
        release.set()
        await writer.stop()
        assert persisted == ([1.0, 2.0] if cancel_route else [1.0, 2.0, 3.0])
    finally:
        if route and not route.done():
            route.cancel()
            await asyncio.gather(route, return_exceptions=True)
        release.set()
        await writer.stop()
