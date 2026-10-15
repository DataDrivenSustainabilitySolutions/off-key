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
                broker_host="127.0.0.1", broker_port=port, subscription_topics=[topic]
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
                    lambda previous=previous: client.client is not None
                    and client.client is not previous
                    and client.is_connected
                )
                await wait_until(lambda previous=previous: previous._thread is None)
                await wait_until(lambda: len(broker._subscriptions.get(topic, [])) == 1)
                await publisher.publish(topic, str(index).encode(), qos=1)
                await wait_until(lambda index=index: len(received) >= index + 1)
            # Give any abandoned Paho automatic reconnect time to reappear.
            await asyncio.sleep(1.2)
            assert len(broker._subscriptions[topic]) == 1
            assert received == [b"0", b"1", b"2"]
            clients.append(client.client)
            await client.stop()
            assert all(not item.is_connected() for item in clients)
            assert all(item._thread is None for item in clients)
        finally:
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
