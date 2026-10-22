"""Real-socket lifecycle contract for the proxy and TACTIC live MQTT clients.

Each client owns its Paho network thread differently, so scenarios apply only
where a client has that path:

| scenario                                  | RADAR | proxy | TACTIC live |
| ----------------------------------------- | ----- | ----- | ----------- |
| stop during in-flight socket creation     | yes   | yes   | yes         |
| withheld CONNACK takes the timeout path   | yes   | yes   | no (retries)|
| one live subscriber after a broker drop   | yes   | yes   | yes         |

The RADAR column lives in test_radar_mqtt_integration.py, which the RADAR
production workflow also runs against its image.
"""

import asyncio
import socket
from contextlib import suppress
from unittest.mock import MagicMock

import pytest
from amqtt.client import MQTTClient as Publisher
from off_key_core.schemas.system import SystemConnection
from off_key_mqtt_proxy.client.connection import ConnectionManager
from off_key_mqtt_proxy.client.facade import MQTTClient
from off_key_mqtt_proxy.client.models import ConnectionState
from off_key_tactic_middleware.services.catalogue.system_live_mqtt import LiveMqttWorker

from tests.support.mqtt import (
    mqtt_broker,
    paused_socket_creation,
    proxy_config,
    wait_until,
    withholding_server,
)

pytestmark = pytest.mark.timeout(15)


def live_worker(port: int, topics: list[str], *, on_message=None, on_state=None):
    return LiveMqttWorker(
        SystemConnection(id="broker", label="Broker", host="127.0.0.1", port=port),
        topics,
        None,
        on_message or MagicMock(),
        on_state or MagicMock(),
    )


async def test_proxy_cancel_during_socket_creation_closes_the_late_socket(
    monkeypatch,
):
    paused = paused_socket_creation(monkeypatch)
    async with withholding_server("connack") as peer:
        manager = ConnectionManager(proxy_config(peer.port))
        connecting = asyncio.create_task(manager.connect())
        try:
            async with asyncio.timeout(5):
                await paused.created.wait()
            network_client = manager.client
            connecting.cancel()
            await wait_until(lambda: manager.client is None)
            paused.release.set()
            async with asyncio.timeout(5):
                with pytest.raises(asyncio.CancelledError):
                    await connecting
            assert manager.state is ConnectionState.FAILED
            assert network_client._thread is None
            assert network_client.socket() is None
            await wait_until(lambda: not peer.writers)
        finally:
            paused.release.set()
            connecting.cancel()
            with suppress(asyncio.CancelledError):
                await connecting
            await manager.disconnect()


async def test_proxy_withheld_connack_times_out_without_a_socket():
    async with withholding_server("connack") as peer:
        manager = ConnectionManager(proxy_config(peer.port))
        try:
            connecting = asyncio.create_task(manager.connect())
            async with asyncio.timeout(5):
                await peer.accepted.wait()
            network_client = manager.client
            assert await connecting is False
            assert manager.state is ConnectionState.FAILED
            assert manager.client is None
            assert network_client._thread is None
            assert network_client.socket() is None
            await wait_until(lambda: not peer.writers)
        finally:
            await manager.disconnect()


async def test_proxy_reconnect_after_broker_drop_keeps_one_subscriber():
    topic = "telemetry/proxy-contract/value"
    received = []
    async with mqtt_broker() as (broker, port):
        client = MQTTClient(proxy_config(port))
        client.set_message_handler(lambda message: received.append(message.payload))
        publisher = Publisher(client_id="proxy-contract-publisher")
        try:
            assert await client.connect()
            assert await client.subscribe(topic)
            await publisher.connect(f"mqtt://127.0.0.1:{port}")
            for index in range(2):
                previous = client.connection_manager.client
                previous.socket().shutdown(socket.SHUT_RDWR)
                await wait_until(lambda: not client.is_connected)
                # The collection loop owns reconnects: connect, then restore
                # whatever the new client generation has not acknowledged.
                assert await client.connect()
                subscriptions = client.subscription_manager
                for missing in {topic} - subscriptions.get_subscriptions():
                    assert await client.subscribe(missing)
                assert previous._thread is None
                await wait_until(lambda: len(broker._subscriptions.get(topic, [])) == 1)
                await publisher.publish(topic, str(index).encode(), qos=1)
                await wait_until(lambda index=index: len(received) == index + 1)
            assert received == [0, 1]  # The proxy decodes JSON payloads.
        finally:
            await client.disconnect()
            await publisher.disconnect()


async def test_live_stop_during_socket_creation_closes_the_late_socket(monkeypatch):
    paused = paused_socket_creation(monkeypatch)
    async with withholding_server("connack") as peer:
        worker = live_worker(peer.port, ["room/values"])
        worker.start()
        try:
            async with asyncio.timeout(5):
                await paused.created.wait()
            # stop() joins the network thread, which waits on the paused socket.
            stopping = asyncio.create_task(asyncio.to_thread(worker.stop))
            await asyncio.sleep(0.1)
            assert not stopping.done()
            paused.release.set()
            async with asyncio.timeout(5):
                await stopping
            assert worker.client._thread is None
            assert worker.client.socket() is None
            await wait_until(lambda: not peer.writers)
        finally:
            paused.release.set()
            await asyncio.to_thread(worker.stop)


async def test_live_reconnect_after_broker_drop_keeps_one_subscriber():
    topic = "room/live-contract/value"
    received, states = [], []
    async with mqtt_broker() as (broker, port):
        worker = live_worker(
            port,
            [topic],
            on_message=lambda topic, payload, retain: received.append(payload),
            on_state=lambda state, detail: states.append(state),
        )
        publisher = Publisher(client_id="live-contract-publisher")
        worker.start()
        try:
            await wait_until(lambda: states[-1:] == ["connected"])
            await publisher.connect(f"mqtt://127.0.0.1:{port}")
            for index in range(2):
                states.clear()
                worker.client.socket().shutdown(socket.SHUT_RDWR)
                # Paho's own bounded backoff reconnects; _connected resubscribes.
                await wait_until(lambda: states[-1:] == ["connected"])
                assert "reconnecting" in states
                await wait_until(lambda: len(broker._subscriptions.get(topic, [])) == 1)
                await publisher.publish(topic, str(index).encode(), qos=1)
                await wait_until(lambda index=index: len(received) == index + 1)
            assert received == [b"0", b"1"]
        finally:
            await asyncio.to_thread(worker.stop)
            await publisher.disconnect()
