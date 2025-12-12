import asyncio
import time
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
from typing import List

import pytest

from off_key_mqtt_proxy.client.messaging import MessageHandler
from off_key_mqtt_proxy.client.connection import ConnectionManager
from off_key_mqtt_proxy.client.models import MQTTMessage
from off_key_mqtt_proxy.config.config import MQTTSettings

"""
This test module covers the following risk scenarios:
1. Event loop lifecycle issues
2. Future resource leaks
3. Exception propagation
4. Race conditions
5. Performance degradation
6. Silent failures
"""


class TestMessageHandlerAsyncEvents:
    """Test suite for MessageHandler async event handling"""

    @pytest.fixture
    def message_handler(self):
        """Create MessageHandler instance"""
        handler = MessageHandler(max_queue_size=100)
        yield handler

    @pytest.fixture
    def mock_mqtt_message(self):
        """Create mock MQTT message"""
        msg = Mock()
        msg.topic = "test/topic"
        msg.payload = b'{"key": "value"}'
        msg.qos = 0
        msg.retain = False
        return msg


    @pytest.mark.asyncio
    async def test_event_loop_not_set(self, message_handler, mock_mqtt_message):
        """Test async handler when event loop is not set"""
        handler_called = []

        async def async_handler(message: MQTTMessage):
            handler_called.append(message)

        # Set handler without event loop
        message_handler._event_loop = None
        message_handler.message_handler = async_handler

        # Simulate MQTT message callback
        message_handler._on_message(None, None, mock_mqtt_message)

        # Handler should not be called, error should be logged
        await asyncio.sleep(0.1)
        assert len(handler_called) == 0

    @pytest.mark.asyncio
    async def test_event_loop_closed_before_callback(self, message_handler, mock_mqtt_message):
        """Test run_coroutine_threadsafe when event loop closes between check and execution"""
        handler_called = []

        async def async_handler(message: MQTTMessage):
            handler_called.append(message)

        loop = asyncio.get_running_loop()
        message_handler.set_handler(async_handler, loop)

        # Close the loop before callback
        # Note: We can't actually close the running loop, so we'll mock is_closed()
        with patch.object(loop, 'is_closed', return_value=True):
            message_handler._on_message(None, None, mock_mqtt_message)

        await asyncio.sleep(0.1)
        # Handler should not be called due to closed loop check
        assert len(handler_called) == 0

    @pytest.mark.asyncio
    async def test_run_coroutine_threadsafe_with_stopped_loop(self, message_handler):
        """Test that run_coroutine_threadsafe raises when loop is stopped"""
        async def async_handler(message: MQTTMessage):
            pass

        # Create a new loop and stop it
        new_loop = asyncio.new_event_loop()
        new_loop.close()

        message_handler._event_loop = new_loop
        message_handler.message_handler = async_handler

        mock_msg = Mock()
        mock_msg.topic = "test/topic"
        mock_msg.payload = b'{"test": "data"}'
        mock_msg.qos = 0
        mock_msg.retain = False

        # Should handle gracefully (error logged, no crash)
        message_handler._on_message(None, None, mock_msg)


    @pytest.mark.asyncio
    async def test_future_not_awaited_memory_leak(self, message_handler, mock_mqtt_message):
        """Test that fire-and-forget futures don't cause memory leaks"""
        futures_created = []

        async def slow_handler(message: MQTTMessage):
            await asyncio.sleep(10)  # Long-running handler

        loop = asyncio.get_running_loop()
        message_handler.set_handler(slow_handler, loop)

        # Patch run_coroutine_threadsafe to track futures
        original_rcts = asyncio.run_coroutine_threadsafe

        def tracked_rcts(coro, loop):
            future = original_rcts(coro, loop)
            futures_created.append(future)
            return future

        with patch('asyncio.run_coroutine_threadsafe', side_effect=tracked_rcts):
            # Send multiple messages
            for _ in range(10):
                message_handler._on_message(None, None, mock_mqtt_message)

        await asyncio.sleep(0.1)

        # Verify futures were created
        assert len(futures_created) == 10

        # Clean up pending futures
        for future in futures_created:
            if not future.done():
                future.cancel()

    @pytest.mark.asyncio
    async def test_futures_complete_eventually(self, message_handler, mock_mqtt_message):
        """Test that futures complete and clean up properly"""
        completed_count = []

        async def quick_handler(message: MQTTMessage):
            await asyncio.sleep(0.01)
            completed_count.append(1)

        loop = asyncio.get_running_loop()
        message_handler.set_handler(quick_handler, loop)

        # Send messages
        for _ in range(5):
            message_handler._on_message(None, None, mock_mqtt_message)

        # Wait for all to complete
        await asyncio.sleep(0.2)

        # All should complete
        assert len(completed_count) == 5


    @pytest.mark.asyncio
    async def test_exception_in_async_handler_logged(self, message_handler, mock_mqtt_message):
        """Test that exceptions in async handlers are logged (not silent)"""
        async def failing_handler(message: MQTTMessage):
            raise ValueError("Test exception in async handler")

        loop = asyncio.get_running_loop()
        message_handler.set_handler(failing_handler, loop)

        # Send message - exception should be logged, not crash
        message_handler._on_message(None, None, mock_mqtt_message)

        await asyncio.sleep(0.1)

        # Verify metrics tracked the exception
        assert message_handler.futures_created == 1
        assert message_handler.futures_failed == 1
        assert message_handler.futures_completed == 0
        assert message_handler.handler_errors == 1

    @pytest.mark.asyncio
    async def test_multiple_handler_exceptions_dont_crash(self, message_handler, mock_mqtt_message):
        """Test multiple concurrent exceptions in async handlers"""
        exception_count = []

        async def sometimes_failing_handler(message: MQTTMessage):
            exception_count.append(1)
            if len(exception_count) % 2 == 0:
                raise RuntimeError(f"Exception {len(exception_count)}")
            await asyncio.sleep(0.01)

        loop = asyncio.get_running_loop()
        message_handler.set_handler(sometimes_failing_handler, loop)

        # Send multiple messages
        for _ in range(10):
            message_handler._on_message(None, None, mock_mqtt_message)

        await asyncio.sleep(0.3)

        # All messages processed (some failed, some succeeded)
        assert len(exception_count) == 10
        # Verify metrics tracked failures (every even message fails)
        assert message_handler.futures_created == 10
        assert message_handler.futures_failed == 5
        assert message_handler.futures_completed == 5
        assert message_handler.handler_errors == 5

    @pytest.mark.asyncio
    async def test_exception_doesnt_stop_processing(self, message_handler):
        """Test that handler exception doesn't stop subsequent messages"""
        processed_messages: List[str] = []

        async def selective_failing_handler(message: MQTTMessage):
            if "fail" in message.topic:
                raise ValueError("Intentional failure")
            processed_messages.append(message.topic)

        loop = asyncio.get_running_loop()
        message_handler.set_handler(selective_failing_handler, loop)

        # Send mix of failing and succeeding messages
        topics = ["test/fail", "test/success1", "test/fail2", "test/success2"]
        for topic in topics:
            msg = Mock()
            msg.topic = topic
            msg.payload = b'{"test": "data"}'
            msg.qos = 0
            msg.retain = False
            message_handler._on_message(None, None, msg)

        await asyncio.sleep(0.2)

        # Successful messages should be processed
        assert "test/success1" in processed_messages
        assert "test/success2" in processed_messages
        assert len(processed_messages) == 2


    @pytest.mark.asyncio
    async def test_concurrent_handler_changes(self, message_handler, mock_mqtt_message):
        """Test race condition when handler is changed while messages arrive"""
        handler1_calls = []
        handler2_calls = []

        async def handler1(message: MQTTMessage):
            handler1_calls.append(message.topic)

        async def handler2(message: MQTTMessage):
            handler2_calls.append(message.topic)

        loop = asyncio.get_running_loop()
        message_handler.set_handler(handler1, loop)

        # Send messages while changing handler
        message_handler._on_message(None, None, mock_mqtt_message)
        message_handler.set_handler(handler2, loop)
        message_handler._on_message(None, None, mock_mqtt_message)

        await asyncio.sleep(0.2)

        # Should handle gracefully without crashes
        total_calls = len(handler1_calls) + len(handler2_calls)
        assert total_calls == 2

    @pytest.mark.asyncio
    async def test_handler_cleared_during_processing(self, message_handler, mock_mqtt_message):
        """Test clearing handler while messages are being processed"""
        processing_started = asyncio.Event()
        handler_calls = []

        async def slow_handler(message: MQTTMessage):
            processing_started.set()
            await asyncio.sleep(0.2)
            handler_calls.append(message.topic)

        loop = asyncio.get_running_loop()
        message_handler.set_handler(slow_handler, loop)

        # Start message processing
        message_handler._on_message(None, None, mock_mqtt_message)
        await processing_started.wait()

        # Clear handler while first message is processing
        message_handler.clear_handler()

        # Send another message (should be queued since no handler)
        message_handler._on_message(None, None, mock_mqtt_message)

        await asyncio.sleep(0.3)

        # First message should complete
        assert len(handler_calls) == 1
        # Second message should be queued
        assert message_handler.get_queue_size() == 1

    @pytest.mark.asyncio
    async def test_rapid_message_arrival(self, message_handler):
        """Test system under rapid concurrent message arrival"""
        received_topics = []

        async def handler(message: MQTTMessage):
            received_topics.append(message.topic)
            await asyncio.sleep(0.01)

        loop = asyncio.get_running_loop()
        message_handler.set_handler(handler, loop)

        # Rapidly send many messages
        for i in range(50):
            msg = Mock()
            msg.topic = f"test/topic/{i}"
            msg.payload = b'{"index": ' + str(i).encode() + b'}'
            msg.qos = 0
            msg.retain = False
            message_handler._on_message(None, None, msg)

        # Wait for all to process
        await asyncio.sleep(1.0)

        # All messages should be processed
        assert len(received_topics) == 50


    @pytest.mark.asyncio
    async def test_message_queue_overflow(self, message_handler):
        """Test behavior when message queue exceeds max size"""
        # Set handler to None so messages are queued
        message_handler.message_handler = None
        max_size = message_handler.max_queue_size

        # Send more messages than max queue size
        for i in range(max_size + 20):
            msg = Mock()
            msg.topic = f"test/topic/{i}"
            msg.payload = b'{"index": ' + str(i).encode() + b'}'
            msg.qos = 0
            msg.retain = False
            message_handler._on_message(None, None, msg)

        # Queue should be at max size, additional messages dropped
        assert message_handler.get_queue_size() == max_size

    @pytest.mark.asyncio
    async def test_slow_handler_doesnt_block_mqtt_callbacks(self, message_handler):
        """Test that slow async handlers don't block MQTT callback thread"""
        call_times = []

        async def very_slow_handler(message: MQTTMessage):
            call_times.append(time.time())
            await asyncio.sleep(0.1)

        loop = asyncio.get_running_loop()
        message_handler.set_handler(very_slow_handler, loop)

        # Rapidly send messages
        start_time = time.time()
        for i in range(5):
            msg = Mock()
            msg.topic = f"test/topic/{i}"
            msg.payload = b'{"test": "data"}'
            msg.qos = 0
            msg.retain = False
            message_handler._on_message(None, None, msg)

        send_time = time.time() - start_time

        # Sending should be fast (not blocked by handler execution)
        assert send_time < 0.5

        # Wait for processing
        await asyncio.sleep(1.0)

        # All should eventually process
        assert len(call_times) == 5


    @pytest.mark.asyncio
    async def test_metrics_track_messages_received(self, message_handler, mock_mqtt_message):
        """Test that message metrics are properly tracked"""
        initial_count = message_handler.messages_received

        # Send messages
        for _ in range(5):
            message_handler._on_message(None, None, mock_mqtt_message)

        # Metrics should reflect received messages
        assert message_handler.messages_received == initial_count + 5

    @pytest.mark.asyncio
    async def test_last_message_time_updated(self, message_handler, mock_mqtt_message):
        """Test that last message time is tracked"""
        assert message_handler.last_message_time is None

        message_handler._on_message(None, None, mock_mqtt_message)

        assert message_handler.last_message_time is not None
        assert isinstance(message_handler.last_message_time, datetime)

    @pytest.mark.asyncio
    async def test_metrics_visibility(self, message_handler, mock_mqtt_message):
        """Test that metrics are accessible for monitoring"""
        async def handler(message: MQTTMessage):
            pass

        loop = asyncio.get_running_loop()
        message_handler.set_handler(handler, loop)

        # Send some messages
        for _ in range(3):
            message_handler._on_message(None, None, mock_mqtt_message)

        await asyncio.sleep(0.1)  # Wait for futures to complete

        metrics = message_handler.get_metrics()

        assert metrics["messages_received"] == 3
        assert metrics["has_handler"] is True
        assert "queue_size" in metrics
        assert "last_message_time" in metrics
        # Verify new metrics are tracked
        assert "handler_errors" in metrics
        assert "futures_created" in metrics
        assert "futures_completed" in metrics
        assert "futures_failed" in metrics
        assert metrics["futures_created"] == 3
        assert metrics["futures_completed"] == 3
        assert metrics["futures_failed"] == 0

    # Edge Cases
    # ==========

    @pytest.mark.asyncio
    async def test_sync_handler_still_works(self, message_handler, mock_mqtt_message):
        """Test that synchronous handlers still work correctly"""
        sync_calls = []

        def sync_handler(message: MQTTMessage):
            sync_calls.append(message.topic)

        message_handler.set_handler(sync_handler)

        # Send messages
        for _ in range(3):
            message_handler._on_message(None, None, mock_mqtt_message)

        # Sync handler should be called immediately
        assert len(sync_calls) == 3

    @pytest.mark.asyncio
    async def test_malformed_json_payload(self, message_handler):
        """Test handling of malformed JSON payloads"""
        handler_calls = []

        async def handler(message: MQTTMessage):
            handler_calls.append(message)

        loop = asyncio.get_running_loop()
        message_handler.set_handler(handler, loop)

        msg = Mock()
        msg.topic = "test/topic"
        msg.payload = b'invalid json {'
        msg.qos = 0
        msg.retain = False

        # Should handle gracefully
        message_handler._on_message(None, None, msg)

        await asyncio.sleep(0.1)

        # Handler should still be called with fallback payload
        assert len(handler_calls) == 1
        assert "raw" in handler_calls[0].payload

    @pytest.mark.asyncio
    async def test_empty_payload(self, message_handler):
        """Test handling of empty message payloads"""
        handler_calls = []

        async def handler(message: MQTTMessage):
            handler_calls.append(message)

        loop = asyncio.get_running_loop()
        message_handler.set_handler(handler, loop)

        msg = Mock()
        msg.topic = "test/topic"
        msg.payload = b''
        msg.qos = 0
        msg.retain = False

        message_handler._on_message(None, None, msg)

        await asyncio.sleep(0.1)

        assert len(handler_calls) == 1


class TestConnectionManagerAsyncEvents:
    """Test suite for ConnectionManager async event handling"""

    @pytest.fixture
    def config(self):
        """Create test MQTT config"""
        return MQTTSettings().config

    @pytest.fixture
    async def connection_manager(self, config):
        """Create ConnectionManager instance"""
        manager = ConnectionManager(config)
        yield manager
        # Cleanup
        if manager._reconnect_task and not manager._reconnect_task.done():
            manager._reconnect_task.cancel()
            try:
                await manager._reconnect_task
            except asyncio.CancelledError:
                pass

    # Event Loop Coordination Tests
    # ==============================

    @pytest.mark.asyncio
    async def test_disconnect_callback_with_event_loop(self, connection_manager):
        """Test disconnect callback coordination through event loop"""
        callback_called = []

        async def on_disconnected(unexpected: bool):
            callback_called.append(unexpected)

        connection_manager.on_disconnected = on_disconnected
        connection_manager._event_loop = asyncio.get_running_loop()

        # Simulate disconnect
        connection_manager._on_disconnect(None, None, 0)

        await asyncio.sleep(0.1)

        # Callback should be called
        assert len(callback_called) == 1
        assert callback_called[0] is False  # Normal disconnect

    @pytest.mark.asyncio
    async def test_disconnect_callback_without_event_loop(self, connection_manager):
        """Test disconnect callback when event loop is not set"""
        callback_called = []

        async def on_disconnected(unexpected: bool):
            callback_called.append(unexpected)

        connection_manager.on_disconnected = on_disconnected
        connection_manager._event_loop = None

        # Simulate disconnect
        connection_manager._on_disconnect(None, None, 0)

        await asyncio.sleep(0.1)

        # Callback should not be called (no event loop)
        assert len(callback_called) == 0

    @pytest.mark.asyncio
    async def test_reconnect_scheduling_with_closed_loop(self, connection_manager):
        """Test reconnect scheduling when event loop is closed"""
        loop = asyncio.get_running_loop()
        connection_manager._event_loop = loop

        # Mock is_closed to return True
        with patch.object(loop, 'is_closed', return_value=True):
            connection_manager._schedule_reconnect()

        # Should log warning and not crash
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_reconnect_task_cleanup_on_shutdown(self, connection_manager):
        """Test that reconnect task is properly cleaned up on shutdown"""
        connection_manager._event_loop = asyncio.get_running_loop()
        connection_manager._shutdown_event.set()

        # Try to schedule reconnect while shutdown
        connection_manager._schedule_reconnect()

        await asyncio.sleep(0.1)

        # No reconnect task should be created
        assert connection_manager._reconnect_task is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
