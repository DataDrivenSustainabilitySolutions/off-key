"""Async event handling in the MQTT proxy without a broker.

Covers event-loop lifecycle, bounded async dispatch, handler failures and
reconnect scheduling of the message handler and connection manager.
"""

import asyncio
from contextlib import suppress
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
import pytest_asyncio
from off_key_mqtt_proxy.client.connection import ConnectionManager
from off_key_mqtt_proxy.client.messaging import MessageHandler
from off_key_mqtt_proxy.client.models import MQTTMessage
from off_key_mqtt_proxy.config.config import MQTTSettings


@pytest_asyncio.fixture
async def message_handler():
    handler = MessageHandler(max_queue_size=100)
    yield handler
    await handler.stop(drain=False)


@pytest_asyncio.fixture
async def connection_manager():
    manager = ConnectionManager(MQTTSettings().config)
    yield manager
    if manager._reconnect_task and not manager._reconnect_task.done():
        manager._reconnect_task.cancel()
        with suppress(asyncio.CancelledError):
            await manager._reconnect_task


def _paho_message(topic="test/topic", payload=b'{"key": "value"}'):
    return Mock(topic=topic, payload=payload, qos=0, retain=False)


def _recorder():
    received = []

    async def handler(message: MQTTMessage):
        received.append(message)

    return handler, received


async def _settle():
    """Run thread-safe callbacks and the tasks they start without sleeping."""
    for _ in range(3):
        await asyncio.sleep(0)


async def _drain(message_handler):
    await _settle()
    await message_handler._handler_queue.join()


@pytest.mark.parametrize("loop_state", ["missing", "closed", "closing"])
async def test_async_handler_without_a_usable_loop_is_never_scheduled(
    message_handler, loop_state
):
    handler, received = _recorder()
    loop = asyncio.new_event_loop()
    if loop_state == "missing":
        loop.close()
        loop = None
    elif loop_state == "closed":
        loop.close()
    else:
        # The loop closes between the is_closed() check and scheduling.
        loop.call_soon_threadsafe = Mock(side_effect=RuntimeError("closed"))
    message_handler._event_loop = loop
    message_handler.message_handler = handler

    message_handler._on_message(None, None, _paho_message())
    await _settle()

    assert received == []
    assert message_handler.futures_created == 0
    assert message_handler.handler_errors == (loop_state == "closing")
    if loop_state == "closing":
        loop.close()


@pytest.mark.parametrize("released", [True, False], ids=["drained", "timed_out"])
async def test_bounded_async_dispatch_accounts_for_every_message(released):
    message_handler = MessageHandler(max_queue_size=3, max_concurrent_handlers=1)
    release = asyncio.Event()

    async def slow_handler(_: MQTTMessage):
        await release.wait()

    message_handler.set_handler(slow_handler, asyncio.get_running_loop())
    for _ in range(10):
        message_handler._on_message(None, None, _paho_message())
    await _settle()

    created = message_handler.futures_created
    assert created <= 3 + 1  # queue bound plus the one busy worker
    assert created + message_handler.handler_messages_dropped == 10

    if released:
        release.set()
    await message_handler.stop(timeout_seconds=0.05)

    assert message_handler.futures_completed == (created if released else 0)
    assert message_handler._handler_queue is None
    assert message_handler._handler_workers == []


async def test_async_handler_failures_are_counted_without_stopping_dispatch(
    message_handler,
):
    processed = []

    async def handler(message: MQTTMessage):
        if "fail" in message.topic:
            raise ValueError("handler failed")
        processed.append(message.topic)

    message_handler.set_handler(handler, asyncio.get_running_loop())
    for topic in ["test/fail1", "test/ok1", "test/fail2", "test/ok2"]:
        message_handler._on_message(None, None, _paho_message(topic))
    await _drain(message_handler)

    assert sorted(processed) == ["test/ok1", "test/ok2"]
    metrics = message_handler.get_metrics()
    assert (
        metrics["futures_created"],
        metrics["futures_completed"],
        metrics["futures_failed"],
        metrics["handler_errors"],
    ) == (4, 2, 2, 2)


async def test_slow_async_handlers_never_block_the_mqtt_callback(message_handler):
    release = asyncio.Event()
    received = []

    async def slow_handler(message: MQTTMessage):
        await release.wait()
        received.append(message.topic)

    message_handler.set_handler(slow_handler, asyncio.get_running_loop())
    topics = [f"test/topic/{i}" for i in range(50)]
    for topic in topics:
        message_handler._on_message(None, None, _paho_message(topic))

    # Every callback returned while no handler could finish.
    assert received == []
    assert message_handler.messages_received == 50

    release.set()
    await _drain(message_handler)

    assert sorted(received) == sorted(topics)
    assert message_handler.futures_completed == 50


async def test_handler_swap_routes_later_messages_to_the_new_handler(
    message_handler,
):
    loop = asyncio.get_running_loop()
    first, first_received = _recorder()
    second, second_received = _recorder()

    message_handler.set_handler(first, loop)
    message_handler._on_message(None, None, _paho_message("test/one"))
    message_handler.set_handler(second, loop)
    message_handler._on_message(None, None, _paho_message("test/two"))
    await _drain(message_handler)

    assert [m.topic for m in first_received] == ["test/one"]
    assert [m.topic for m in second_received] == ["test/two"]


async def test_clearing_the_handler_queues_later_messages_while_work_finishes(
    message_handler,
):
    started, release = asyncio.Event(), asyncio.Event()
    handled = []

    async def slow_handler(message: MQTTMessage):
        started.set()
        await release.wait()
        handled.append(message.topic)

    message_handler.set_handler(slow_handler, asyncio.get_running_loop())
    message_handler._on_message(None, None, _paho_message())
    await started.wait()

    message_handler.clear_handler()
    message_handler._on_message(None, None, _paho_message())
    release.set()
    await message_handler._handler_queue.join()

    assert handled == ["test/topic"]
    assert message_handler.get_queue_size() == 1


async def test_messages_without_a_handler_are_queued_up_to_the_bound(
    message_handler,
):
    assert message_handler.last_message_time is None
    bound = message_handler.max_queue_size
    for i in range(bound + 20):
        message_handler._on_message(None, None, _paho_message(f"test/topic/{i}"))
    # Oversized payloads are rejected before parsing or counting.
    message_handler._on_message(None, None, _paho_message(payload=b"x" * 40_000))

    assert message_handler.messages_received == bound + 20
    assert message_handler.handler_messages_dropped == 1
    assert isinstance(message_handler.last_message_time, datetime)
    assert message_handler.get_queue_size() == bound
    first_two = message_handler.get_queued_messages(2)
    rest = message_handler.get_queued_messages()
    assert [m.topic for m in first_two + rest] == [
        f"test/topic/{i}" for i in range(bound)
    ]
    assert message_handler.get_queue_size() == 0


@pytest.mark.parametrize(
    ("connected_seconds_ago", "has_messages", "expected"),
    [(10, True, 0.5), (None, True, 0.0), (10, False, 0.0), (-10, True, 0.0)],
    ids=["rate", "not_connected", "no_messages", "clock_skew"],
)
def test_message_rate_is_messages_per_connected_second(
    connected_seconds_ago, has_messages, expected
):
    message_handler = MessageHandler()
    message_handler.messages_received = 5
    if has_messages:
        message_handler.last_message_time = datetime.now()
    connected_at = (
        None
        if connected_seconds_ago is None
        else datetime.now() - timedelta(seconds=connected_seconds_ago)
    )

    rate = message_handler.get_message_rate(connected_at)

    assert rate == pytest.approx(expected, rel=0.05)


async def test_metrics_report_completed_async_work(message_handler):
    handler, _ = _recorder()
    message_handler.set_handler(handler, asyncio.get_running_loop())
    for _ in range(3):
        message_handler._on_message(None, None, _paho_message())
    await _drain(message_handler)

    assert message_handler.get_metrics() == {
        "messages_received": 3,
        "queue_size": 0,
        "max_queue_size": 100,
        "last_message_time": message_handler.last_message_time.isoformat(),
        "has_handler": True,
        "handler_errors": 0,
        "futures_created": 3,
        "futures_completed": 3,
        "futures_failed": 0,
        "handler_queue_size": 0,
        "handler_messages_dropped": 0,
    }


async def test_sync_handlers_run_inline_and_failures_are_counted(message_handler):
    calls = []

    def sync_handler(message: MQTTMessage):
        calls.append(message.topic)
        if len(calls) == 2:
            raise RuntimeError("sync handler failed")

    message_handler.set_handler(sync_handler)
    for _ in range(3):
        message_handler._on_message(None, None, _paho_message())

    assert calls == ["test/topic"] * 3
    assert message_handler.handler_errors == 1


@pytest.mark.parametrize("payload", [b"invalid json {", b""])
async def test_undecodable_payload_reaches_the_handler_as_raw_text(
    message_handler, payload
):
    handler, received = _recorder()
    message_handler.set_handler(handler, asyncio.get_running_loop())

    message_handler._on_message(None, None, _paho_message(payload=payload))
    await _drain(message_handler)

    assert [m.payload for m in received] == [{"raw": payload.decode()}]


@pytest.mark.parametrize(
    ("reason_code", "has_loop", "notified", "reconnects"),
    [(0, True, [False], False), (0, False, [], False), (1, True, [True], True)],
    ids=["clean", "clean_without_loop", "unexpected"],
)
async def test_disconnect_notifies_through_the_loop_and_reconnects_when_unexpected(
    connection_manager, reason_code, has_loop, notified, reconnects
):
    received = []

    async def on_disconnected(unexpected: bool):
        received.append(unexpected)

    connection_manager.on_disconnected = on_disconnected
    connection_manager._event_loop = asyncio.get_running_loop() if has_loop else None
    connection_manager._reconnect_loop = AsyncMock()

    connection_manager._on_disconnect(None, None, reason_code)
    await _settle()

    assert received == notified
    assert (connection_manager._reconnect_task is not None) == reconnects


async def test_disconnect_from_a_retired_client_is_ignored(connection_manager):
    connection_manager.client = MagicMock()
    connection_manager._event_loop = asyncio.get_running_loop()
    connection_manager.on_disconnected = MagicMock()

    connection_manager._on_disconnect(MagicMock(), None, 1)
    await _settle()

    connection_manager.on_disconnected.assert_not_called()
    assert connection_manager._reconnect_task is None


@pytest.mark.parametrize("cause", ["closed_loop", "shutdown"])
async def test_reconnect_is_not_scheduled_without_a_live_loop_or_after_shutdown(
    connection_manager, cause
):
    loop = asyncio.get_running_loop()
    connection_manager._event_loop = loop
    if cause == "shutdown":
        connection_manager._shutdown_event.set()
        connection_manager._schedule_reconnect()
    else:
        with patch.object(loop, "is_closed", return_value=True):
            connection_manager._schedule_reconnect()
    await _settle()

    assert connection_manager._reconnect_task is None


async def test_connect_clears_stale_connection_event(connection_manager):
    """Test that reconnect attempts cannot reuse a stale success event."""
    connection_manager._connection_event.set()

    mock_client = MagicMock()
    mock_client.connect_async = MagicMock()
    mock_client.loop_start = MagicMock()
    mock_client.loop_stop = MagicMock()
    mock_client.disconnect = MagicMock()
    event_was_cleared = False

    async def fake_wait_for(awaitable, timeout):  # noqa: ASYNC109
        nonlocal event_was_cleared
        awaitable.close()
        event_was_cleared = not connection_manager._connection_event.is_set()
        raise TimeoutError

    with (
        patch(
            "off_key_mqtt_proxy.client.connection.mqtt.Client",
            return_value=mock_client,
        ),
        patch("asyncio.wait_for", side_effect=fake_wait_for),
    ):
        assert await connection_manager.connect() is False

    assert event_was_cleared, "_connection_event should be cleared before wait"
    mock_client.loop_stop.assert_called_once()
    mock_client.disconnect.assert_called_once()
