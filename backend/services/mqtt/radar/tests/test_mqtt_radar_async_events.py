"""Async event handling in the RADAR MQTT client without a broker.

Covers event-loop lifecycle, handler failures, shutdown, admission bounds and
reconnection. Real-broker behaviour lives in test_radar_mqtt_integration.py.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
import pytest_asyncio
from off_key_mqtt_radar.config.config import MQTTRadarConfig
from off_key_mqtt_radar.models import MQTTMessage
from off_key_mqtt_radar.mqtt_client import RadarMQTTClient


@pytest.fixture
def config():
    return MQTTRadarConfig(
        broker_host="localhost",
        broker_port=1883,
        use_tls=False,
        use_auth=False,
        subscription_topics=["telemetry/test/sine"],
        subscription_qos=0,
        max_queue_size=100,
        rate_limit_per_minute=60,
        client_id_prefix="test",
    )


@pytest_asyncio.fixture
async def mqtt_client(config):
    """Client whose connect step installs a mocked Paho client."""
    client = RadarMQTTClient(config)
    paho_client = MagicMock(_client_id="test-client-id")

    async def connect():
        client._loop = asyncio.get_running_loop()
        client.client = paho_client
        client.is_connected = True

    client._connect = connect
    yield client
    await client.stop()


def _message(payload=b"test"):
    return MQTTMessage(
        topic="test/topic",
        payload=payload,
        qos=0,
        retain=False,
        timestamp=datetime.now(),
    )


def _drops(client):
    return client.coverage.snapshot().dropped_by_reason


async def test_message_before_the_loop_is_ready_is_counted_as_dropped(mqtt_client):
    paho_message = Mock(topic="test/topic", payload=b"test", qos=0, retain=False)

    mqtt_client._on_message(None, None, paho_message)

    assert mqtt_client.message_queue.qsize() == 0
    assert _drops(mqtt_client) == {"loop_unavailable": 1}


async def test_messages_after_shutdown_are_ignored(mqtt_client):
    await mqtt_client.start()
    await mqtt_client.stop()

    mqtt_client._on_message(mqtt_client.client, None, Mock(payload=b"test"))

    assert mqtt_client.coverage.snapshot().received_message_count == 0


async def test_message_racing_shutdown_is_accounted_as_dropped(mqtt_client):
    """Paho can pass the shutdown check just before stop() closes the bridge."""
    await mqtt_client.start()
    await mqtt_client.stop()

    mqtt_client._handle_incoming_message(_message())

    assert mqtt_client.error_count == 1
    assert _drops(mqtt_client) == {"enqueue_error": 1}


async def test_start_fails_when_initial_connect_fails(config):
    """Test startup does not mark the client running without MQTT connectivity."""
    client = RadarMQTTClient(config)
    client._connect = AsyncMock(side_effect=RuntimeError("connect failed"))

    with pytest.raises(RuntimeError, match="connect failed"):
        await client.start()

    assert client._shutdown_event.is_set()
    assert client.is_connected is False
    assert (
        client._message_processor_task is None or client._message_processor_task.done()
    )


async def test_connect_completes_from_success_callback(config):
    """The Paho callback resolves the connection attempt without polling."""
    paho_client = MagicMock()
    paho_client.subscribe.return_value = (0, 1)

    def acknowledge_subscription():
        paho_client.on_connect(paho_client, None, None, 0, None)
        assert client.is_connected is False
        paho_client.on_subscribe(paho_client, None, 1, [0], None)

    paho_client.loop_start.side_effect = acknowledge_subscription
    client = RadarMQTTClient(config)

    with patch("off_key_mqtt_radar.mqtt_client.mqtt.Client", return_value=paho_client):
        await asyncio.wait_for(client._connect(), timeout=0.5)

    assert client.is_connected is True
    assert client._connection_result is None
    paho_client.subscribe.assert_called_once()
    await client.stop()


async def test_connect_fails_from_refusal_callback(config):
    """A broker refusal fails immediately instead of waiting for a timeout."""
    paho_client = MagicMock()
    paho_client.loop_start.side_effect = lambda: paho_client.on_connect(
        paho_client, None, None, 5
    )
    client = RadarMQTTClient(config)

    with (
        patch(
            "off_key_mqtt_radar.mqtt_client.mqtt.Client",
            return_value=paho_client,
        ),
        pytest.raises(RuntimeError, match="not authorized"),
    ):
        await asyncio.wait_for(client._connect(), timeout=0.5)

    assert client.is_connected is False
    assert client._connection_result is None
    assert client.client is None


async def test_local_subscribe_failure_never_marks_ready(config):
    paho_client = MagicMock()
    paho_client.subscribe.return_value = (4, None)
    paho_client.loop_start.side_effect = lambda: paho_client.on_connect(
        paho_client, None, None, 0, None
    )
    client = RadarMQTTClient(config)
    with (
        patch("off_key_mqtt_radar.mqtt_client.mqtt.Client", return_value=paho_client),
        pytest.raises(RuntimeError, match="SUBSCRIBE failed locally"),
    ):
        await client._connect()
    assert not client.is_connected
    assert client.client is None


async def test_handler_failures_are_counted_without_stopping_the_processor(
    mqtt_client,
):
    await mqtt_client.start()
    processed = []

    async def handler(message: MQTTMessage):
        if message.payload.startswith(b"fail"):
            raise ValueError("handler failed")
        processed.append(message)

    mqtt_client.set_message_handler(handler)
    messages = [_message(payload) for payload in (b"fail", b"ok", b"fail", b"", b"ok")]
    for message in messages:
        await mqtt_client.message_queue.put(message)
    await mqtt_client.message_queue.join()

    # Delivered messages are the queued objects: payload and timestamp untouched.
    delivered = [messages[1], messages[3], messages[4]]
    assert all(got is sent for got, sent in zip(processed, delivered, strict=True))
    assert mqtt_client.error_count == 2
    assert _drops(mqtt_client) == {"handler_error": 2}
    assert not mqtt_client._message_processor_task.done()


async def test_messages_before_a_handler_is_set_are_drained_as_drops(mqtt_client):
    await mqtt_client.start()
    for _ in range(3):
        await mqtt_client.message_queue.put(_message())
    await mqtt_client.message_queue.join()

    handler = AsyncMock()
    mqtt_client.set_message_handler(handler)
    for _ in range(2):
        await mqtt_client.message_queue.put(_message())
    await mqtt_client.message_queue.join()

    assert mqtt_client.message_queue.qsize() == 0
    assert _drops(mqtt_client) == {"no_handler": 3}
    assert handler.await_count == 2


async def test_stop_drops_backlog_that_a_slow_handler_let_accumulate(mqtt_client):
    await mqtt_client.start()
    started, release = asyncio.Event(), asyncio.Event()

    async def slow_handler(_: MQTTMessage):
        started.set()
        await release.wait()

    mqtt_client.set_message_handler(slow_handler)
    await mqtt_client.message_queue.put(_message())
    await started.wait()
    # The network callback keeps admitting while the handler is still busy.
    for _ in range(5):
        mqtt_client._handle_incoming_message(_message())
    assert mqtt_client.message_count == 5

    await mqtt_client.stop()

    assert mqtt_client._message_processor_task.done()
    assert _drops(mqtt_client) == {"shutdown_queue": 5}


async def test_stop_is_idempotent_and_restart_reopens_the_bridge(mqtt_client):
    await mqtt_client.start()
    await mqtt_client.stop()
    await mqtt_client.stop()
    assert mqtt_client._shutdown_event.is_set()
    assert not mqtt_client.is_connected

    handler = AsyncMock()
    mqtt_client.set_message_handler(handler)
    await mqtt_client.start()
    await mqtt_client.message_queue.put(_message())
    await mqtt_client.message_queue.join()

    handler.assert_awaited_once()


async def test_rate_limit_admits_exactly_its_budget_across_network_threads(
    mqtt_client,
):
    limit = mqtt_client.config.rate_limit_per_minute
    messages = [_message() for _ in range(limit + 20)]

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(mqtt_client._handle_incoming_message, messages))

    assert mqtt_client.message_count == limit
    assert mqtt_client.message_queue.qsize() == limit
    assert len(mqtt_client.rate_limiter) == limit
    assert _drops(mqtt_client) == {"rate_limit": 20}


async def test_health_status_degrades_on_a_high_error_rate(mqtt_client):
    await mqtt_client.start()
    mqtt_client.error_count = 50
    mqtt_client.message_count = 100

    health = mqtt_client.get_health_status()

    assert (health["status"], health["reason"]) == ("degraded", "high_error_rate")
    assert health["error_rate"] == 0.5


async def test_unexpected_disconnect_records_a_gap_and_schedules_reconnect(
    mqtt_client,
):
    await mqtt_client.start()

    mqtt_client._on_disconnect(mqtt_client.client, None, None, 1, None)
    await asyncio.sleep(0)  # let the thread-safe reconnect scheduling run

    assert not mqtt_client.is_connected
    assert mqtt_client.get_health_status()["status"] == "unhealthy"
    assert mqtt_client.coverage.snapshot().last_gap_reason == "mqtt_disconnect"
    assert mqtt_client._reconnect_task is not None


async def test_reconnection_backoff(config):
    """Test exponential backoff in reconnection attempts"""
    client = RadarMQTTClient(config)
    client.reconnect_delay = 0.01  # Speed up test
    calls = 0

    # Mock _connect to not actually connect
    async def mock_connect():
        nonlocal calls
        calls += 1
        if calls == 3:
            client.is_connected = True

    client._connect = mock_connect

    # Trigger reconnection
    client._ensure_reconnect_task()
    if client._reconnect_task:
        await asyncio.wait_for(client._reconnect_task, timeout=1)

    assert calls == 3
    assert client.reconnect_attempts == 3


async def test_reconnection_has_no_attempt_cutoff_or_unbounded_exponent(config):
    """A long-lived retry counter cannot exhaust retries or overflow backoff."""
    client = RadarMQTTClient(config)
    client.reconnect_delay = 0.001
    client.reconnect_attempts = 100000

    async def mock_connect():
        client.is_connected = True

    client._connect = mock_connect

    client._ensure_reconnect_task()
    await asyncio.wait_for(client._reconnect_task, timeout=1)

    assert client.reconnect_attempts == 100001
    assert client.is_connected


async def test_shutdown_interrupts_capped_reconnect_backoff(config):
    client = RadarMQTTClient(config)
    client.reconnect_delay = 300
    client._ensure_reconnect_task()
    await asyncio.sleep(0)  # let the first attempt start before shutdown
    client._shutdown_event.set()
    await asyncio.wait_for(client._reconnect_task, timeout=1)
    assert client.reconnect_attempts == 1
    await client.stop()


async def test_shutdown_cancels_reconnection(config):
    """Test that shutdown prevents reconnection attempts"""
    client = RadarMQTTClient(config)
    client._shutdown_event.set()

    initial_attempts = client.reconnect_attempts

    # Should not reconnect when shutdown
    client._ensure_reconnect_task()
    assert client._reconnect_task is None

    assert client.reconnect_attempts == initial_attempts
