"""RADAR regressions over real loopback MQTT connections, without network mocks."""

import asyncio
import socket
from contextlib import asynccontextmanager

import pytest
from amqtt.broker import Broker
from amqtt.client import MQTTClient
from off_key_mqtt_radar.config.config import MQTTRadarConfig
from off_key_mqtt_radar.mqtt_client import RadarMQTTClient


async def wait_until(predicate, deadline_seconds=10):
    async with asyncio.timeout(deadline_seconds):
        # Broker and Paho thread state do not expose an asyncio event.
        while not predicate():  # noqa: ASYNC110
            await asyncio.sleep(0.01)


@asynccontextmanager
async def mqtt_broker(*, plugins=None):
    broker = Broker(
        {
            "listeners": {"default": {"type": "tcp", "bind": "127.0.0.1:0"}},
            "plugins": plugins
            or {
                "amqtt.plugins.authentication.AnonymousAuthPlugin": {
                    "allow_anonymous": True
                }
            },
        }
    )
    await broker.start()
    port = broker._servers["default"].instance.sockets[0].getsockname()[1]
    try:
        yield broker, port
    finally:
        await broker.shutdown()


async def test_repeated_socket_failures_keep_one_subscriber_and_stop_all_threads():
    topic = "telemetry/reconnect/value"
    async with mqtt_broker() as (broker, port):
        client = RadarMQTTClient(
            MQTTRadarConfig(
                broker_host="127.0.0.1",
                broker_port=port,
                subscription_topics=[topic],
                rate_limit_per_minute=1000,
            )
        )
        client.reconnect_delay = 0.02
        received = []

        async def receive(message):
            received.append(message.payload)

        client.set_message_handler(receive)
        publisher = MQTTClient(client_id="reconnect-regression-publisher")
        clients = []
        try:
            await client.start()
            await publisher.connect(f"mqtt://127.0.0.1:{port}")
            for index in range(3):
                previous = client.client
                clients.append(previous)
                previous.socket().shutdown(socket.SHUT_RDWR)
                await wait_until(
                    lambda previous=previous: (
                        client.client is not None
                        and client.client is not previous
                        and client.is_connected
                    )
                )
                await wait_until(lambda previous=previous: previous._thread is None)
                await wait_until(lambda: len(broker._subscriptions.get(topic, [])) == 1)
                await publisher.publish(topic, str(index).encode(), qos=1)
                await wait_until(lambda index=index: len(received) >= index + 1)
            # Give any abandoned Paho automatic reconnect time to reappear.
            await asyncio.sleep(1.2)
            assert len(broker._subscriptions[topic]) == 1
            assert received == [b"0", b"1", b"2"]
            assert client.coverage.snapshot().possible_gap_count == 3
            assert client.get_health_status()["status"] == "degraded"
            clients.append(client.client)
            await client.stop()
            assert all(not item.is_connected() for item in clients)
            assert all(item._thread is None for item in clients)
        finally:
            await client.stop()
            await publisher.disconnect()


@pytest.mark.parametrize("limit", [0, 1000])
async def test_real_mqtt_burst_exposes_configured_throttling_and_persistent_loss(limit):
    topic = "telemetry/coverage/value"
    async with mqtt_broker() as (_, port):
        client = RadarMQTTClient(
            MQTTRadarConfig(
                broker_host="127.0.0.1",
                broker_port=port,
                subscription_topics=[topic],
                rate_limit_per_minute=limit,
            )
        )
        received = []

        async def receive(message):
            received.append(message.payload)

        client.set_message_handler(receive)
        publisher = MQTTClient(client_id=f"coverage-publisher-{limit}")
        try:
            await client.start()
            await publisher.connect(f"mqtt://127.0.0.1:{port}")
            for _ in range(1100):
                await publisher.publish(topic, b'{"value":42}', qos=1)
            await wait_until(
                lambda: client.coverage.snapshot().received_message_count == 1100
            )
            await wait_until(lambda: len(received) == (1000 if limit else 1100))
            client._emit_drop_summary(force=True)
            coverage = client.get_health_status()["coverage"]
            assert coverage["dropped_message_count"] == (100 if limit else 0)
            assert coverage["has_gaps"] is bool(limit)
            assert client.get_health_status()["status"] == (
                "degraded" if limit else "healthy"
            )
            if not limit:
                assert not client.rate_limiter
        finally:
            await client.stop()
            await publisher.disconnect()


async def test_real_mqtt_queue_overflow_records_every_locally_discarded_message():
    topic = "telemetry/overflow/value"
    async with mqtt_broker() as (_, port):
        client = RadarMQTTClient(
            MQTTRadarConfig(
                broker_host="127.0.0.1",
                broker_port=port,
                subscription_topics=[topic],
                max_queue_size=2,
            )
        )
        processing = asyncio.Event()
        resume = asyncio.Event()

        async def receive(message):
            processing.set()
            await resume.wait()

        client.set_message_handler(receive)
        publisher = MQTTClient(client_id="coverage-overflow-publisher")
        try:
            await client.start()
            await publisher.connect(f"mqtt://127.0.0.1:{port}")
            await publisher.publish(topic, b'{"value":42}', qos=1)
            await processing.wait()
            for _ in range(9):
                await publisher.publish(topic, b'{"value":42}', qos=1)
            await wait_until(
                lambda: client.coverage.snapshot().received_message_count == 10
            )
            coverage = client.coverage.snapshot()
            assert coverage.dropped_message_count == 7
            assert coverage.dropped_by_reason == {"queue_full": 7}
            assert client.get_health_status()["status"] == "degraded"
        finally:
            resume.set()
            await client.stop()
            await publisher.disconnect()


async def test_cancelled_initial_connection_stops_processor_and_network_thread():
    accepted = asyncio.Event()

    async def withhold_connack(reader, writer):
        accepted.set()
        try:
            await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(withhold_connack, "127.0.0.1", 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        client = RadarMQTTClient(
            MQTTRadarConfig(broker_host="127.0.0.1", broker_port=port)
        )
        startup = asyncio.create_task(client.start())
        try:
            async with asyncio.timeout(5):
                await accepted.wait()
            network_client = client.client
            startup.cancel()
            with pytest.raises(asyncio.CancelledError):
                await startup
            assert client._shutdown_event.is_set()
            assert client._message_processor_task.done()
            assert client.client is None
            assert network_client._thread is None
        finally:
            await client.stop()


async def test_real_broker_acl_rejection_fails_required_subscription_readiness():
    plugins = {
        "amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True},
        "amqtt.plugins.topic_checking.TopicAccessControlListPlugin": {
            "acl": {"anonymous": ["telemetry/acl/allowed"]}
        },
    }
    async with mqtt_broker(plugins=plugins) as (_, port):
        client = RadarMQTTClient(
            MQTTRadarConfig(
                broker_host="127.0.0.1",
                broker_port=port,
                subscription_topics=["telemetry/acl/allowed", "telemetry/acl/denied"],
            )
        )
        try:
            with pytest.raises(RuntimeError, match="subscription rejected"):
                await client.start()
            assert not client.is_connected
            assert client.client is None
            assert client.get_health_status()["status"] == "unhealthy"
        finally:
            await client.stop()


async def test_missing_suback_times_out_and_cleans_up_actual_socket():
    subscribed = asyncio.Event()

    async def read_packet(reader):
        header = await reader.readexactly(1)
        size, multiplier = 0, 1
        while True:
            digit = (await reader.readexactly(1))[0]
            size += (digit & 127) * multiplier
            if not digit & 128:
                break
            multiplier *= 128
        return header, await reader.readexactly(size)

    async def withhold_suback(reader, writer):
        try:
            await read_packet(reader)
            writer.write(b"\x20\x02\x00\x00")  # Real MQTT 3.1.1 CONNACK.
            await writer.drain()
            await read_packet(reader)
            subscribed.set()
            await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(withhold_suback, "127.0.0.1", 0)
    async with server:
        client = RadarMQTTClient(
            MQTTRadarConfig(
                broker_host="127.0.0.1",
                broker_port=server.sockets[0].getsockname()[1],
            )
        )
        client._connection_timeout_seconds = 0.3
        startup = asyncio.create_task(client.start())
        try:
            async with asyncio.timeout(5):
                await subscribed.wait()
            network_client = client.client
            assert not client.is_connected
            with pytest.raises(RuntimeError, match="acknowledgement timed out"):
                await startup
            assert client.client is None
            assert network_client._thread is None
        finally:
            await client.stop()
