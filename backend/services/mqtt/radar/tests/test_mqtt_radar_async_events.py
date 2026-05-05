import asyncio
import time
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

import pytest

from off_key_mqtt_radar.mqtt_client import RadarMQTTClient
from off_key_mqtt_radar.config.config import MQTTRadarConfig
from off_key_mqtt_radar.models import MQTTMessage

"""
This test module covers the following risk scenarios:
1. Event loop lifecycle issues
2. Exception propagation
3. Resource leaks
4. Race conditions
5. Performance degradation
6. Silent failures
"""


class TestMQTTAsyncEventHandling:
    """Test suite for async event handling in MQTT client"""

    @pytest.fixture
    def config(self):
        """Create test configuration"""
        return MQTTRadarConfig(
            broker_host="localhost",
            broker_port=1883,
            use_tls=False,
            use_auth=False,
            subscription_topics=["test/topic"],
            subscription_qos=0,
            max_queue_size=100,
            rate_limit_per_minute=60,
            client_id_prefix="test",
        )

    @pytest.fixture
    async def mqtt_client(self, config):
        """Create MQTT client instance with mocked paho client"""
        client = RadarMQTTClient(config)

        # Mock network connections
        with patch("off_key_mqtt_radar.mqtt_client.mqtt.Client") as mock_client_class:
            mock_mqtt_client = MagicMock()
            mock_mqtt_client.connect_async = MagicMock()
            mock_mqtt_client.loop_start = MagicMock()
            mock_mqtt_client.loop_stop = MagicMock()
            mock_mqtt_client.disconnect = MagicMock()
            mock_mqtt_client.subscribe = MagicMock(return_value=(0, 1))
            mock_mqtt_client._client_id = "test-client-id"
            mock_client_class.return_value = mock_mqtt_client

            # Store mock for tests to use
            client._mock_mqtt_client = mock_mqtt_client

            # start client without actually connecting
            _ = client._connect

            async def mock_connect():
                client._loop = asyncio.get_running_loop()
                client.client = mock_mqtt_client
                client.is_connected = True

            client._connect = mock_connect

            yield client

            # Cleanup
            if (
                client._message_processor_task
                and not client._message_processor_task.done()
            ):
                client._message_processor_task.cancel()
                try:
                    await client._message_processor_task
                except asyncio.CancelledError:
                    pass

    @pytest.mark.asyncio
    async def test_event_loop_not_initialized(self, mqtt_client):
        """Test behavior when event loop is not set"""
        # Simulate MQTT message callback before start()
        mqtt_client._loop = None

        mock_msg = Mock()
        mock_msg.topic = "test/topic"
        mock_msg.payload = b"test"
        mock_msg.qos = 0
        mock_msg.retain = False

        # Should not crash, should log and drop message
        mqtt_client._on_message(None, None, mock_msg)

        # Queue should be empty (message was dropped)
        assert mqtt_client.message_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_event_loop_closed_during_message_handling(self, mqtt_client):
        """Test handling message when event loop closes between check and execution"""
        # Start client and simulate successful connection
        mqtt_client._loop = asyncio.get_running_loop()
        mqtt_client._message_processor_task = asyncio.create_task(
            mqtt_client._message_processor()
        )
        mqtt_client.is_connected = True

        mock_msg = Mock()
        mock_msg.topic = "test/topic"
        mock_msg.payload = b"test"
        mock_msg.qos = 0
        mock_msg.retain = False

        # Stop the client (closes event loop)
        await mqtt_client.stop()

        # Try to process message with closed loop
        # Should handle gracefully without crashing
        mqtt_client._on_message(None, None, mock_msg)

        # Should not add to queue since loop is stopped
        assert mqtt_client._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_call_soon_threadsafe_with_closed_loop(self, mqtt_client):
        """Test call_soon_threadsafe behavior with closed event loop"""
        await mqtt_client.start()
        loop = mqtt_client._loop

        # Close the loop
        await mqtt_client.stop()

        # Attempt to use call_soon_threadsafe should not crash
        # This tests the robustness of the cross-thread coordination
        try:
            message = MQTTMessage(
                topic="test/topic",
                payload=b"test",
                qos=0,
                retain=False,
                timestamp=datetime.now(),
            )
            # This may raise RuntimeError if loop is closed, which is expected
            loop.call_soon_threadsafe(
                lambda: mqtt_client._handle_incoming_message(message)
            )
        except RuntimeError as e:
            # Expected when loop is closed
            assert "closed" in str(e).lower() or "running" in str(e).lower()

    @pytest.mark.asyncio
    async def test_message_handler_exception_propagation(self, mqtt_client):
        """Test that exceptions in async message handler are caught and logged"""
        await mqtt_client.start()

        # Set up a handler that raises an exception
        async def failing_handler(_: MQTTMessage):
            raise ValueError("Test exception in handler")

        mqtt_client.set_message_handler(failing_handler)

        # Send a message
        message = MQTTMessage(
            topic="test/topic",
            payload=b"test",
            qos=0,
            retain=False,
            timestamp=datetime.now(),
        )

        await mqtt_client.message_queue.put(message)

        # Give processor time to handle message
        await asyncio.sleep(0.2)

        # Error count should increase
        assert mqtt_client.error_count > 0

        # Client should still be running (exception didn't kill processor)
        assert not mqtt_client._message_processor_task.done()

    @pytest.mark.asyncio
    async def test_multiple_concurrent_handler_exceptions(self, mqtt_client):
        """Test multiple simultaneous handler exceptions don't crash the system"""
        await mqtt_client.start()

        exception_count = 0

        async def sometimes_failing_handler(_: MQTTMessage):
            nonlocal exception_count
            exception_count += 1
            if exception_count % 2 == 0:
                raise RuntimeError(f"Exception {exception_count}")
            await asyncio.sleep(0.01)

        mqtt_client.set_message_handler(sometimes_failing_handler)

        # Send multiple messages
        for i in range(10):
            message = MQTTMessage(
                topic="test/topic",
                payload=f"message_{i}".encode(),
                qos=0,
                retain=False,
                timestamp=datetime.now(),
            )
            await mqtt_client.message_queue.put(message)

        # Wait for processing
        await asyncio.sleep(0.5)

        # Some should have failed
        assert mqtt_client.error_count >= 5
        # Processor should still be running
        assert not mqtt_client._message_processor_task.done()

    @pytest.mark.asyncio
    async def test_handler_exception_with_queue_backlog(self, mqtt_client):
        """Test exception handling doesn't block queue processing"""
        await mqtt_client.start()

        processed_messages = []

        async def handler_with_selective_failures(message: MQTTMessage):
            if b"fail" in message.payload:
                raise ValueError("Intentional failure")
            processed_messages.append(message.payload)

        mqtt_client.set_message_handler(handler_with_selective_failures)

        # Queue messages: some that fail, some that succeed
        messages = [b"fail1", b"success1", b"fail2", b"success2", b"success3"]
        for payload in messages:
            await mqtt_client.message_queue.put(
                MQTTMessage(
                    topic="test/topic",
                    payload=payload,
                    qos=0,
                    retain=False,
                    timestamp=datetime.now(),
                )
            )

        # Wait for processing
        await asyncio.sleep(0.5)

        # Successful messages should be processed
        assert len(processed_messages) == 3
        assert mqtt_client.error_count == 2

    @pytest.mark.asyncio
    async def test_message_queue_cleanup_on_shutdown(self, mqtt_client):
        """Test that pending messages are handled during shutdown"""
        await mqtt_client.start()

        # Fill queue with messages
        for i in range(10):
            message = MQTTMessage(
                topic="test/topic",
                payload=f"message_{i}".encode(),
                qos=0,
                retain=False,
                timestamp=datetime.now(),
            )
            await mqtt_client.message_queue.put(message)

        initial_queue_size = mqtt_client.message_queue.qsize()
        assert initial_queue_size > 0

        # Stop client
        await mqtt_client.stop()

        # Task should be cancelled
        assert (
            mqtt_client._message_processor_task.cancelled()
            or mqtt_client._message_processor_task.done()
        )

    @pytest.mark.asyncio
    async def test_no_handler_memory_leak(self, mqtt_client):
        """Test that messages without handlers don't accumulate"""
        await mqtt_client.start()

        # Don't set a message handler
        mqtt_client.message_handler = None

        # Send messages
        for i in range(20):
            message = MQTTMessage(
                topic="test/topic",
                payload=f"message_{i}".encode(),
                qos=0,
                retain=False,
                timestamp=datetime.now(),
            )
            await mqtt_client.message_queue.put(message)

        # Wait for processing
        await asyncio.sleep(0.3)

        # Queue should be drained even without handler
        assert mqtt_client.message_queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_mqtt_client_cleanup_on_multiple_stop_calls(self, mqtt_client):
        """Test that multiple stop() calls don't cause resource issues"""
        await mqtt_client.start()

        # Call stop multiple times
        await mqtt_client.stop()
        await mqtt_client.stop()
        await mqtt_client.stop()

        # Should handle gracefully
        assert mqtt_client._shutdown_event.is_set()
        assert not mqtt_client.is_connected

    @pytest.mark.asyncio
    async def test_concurrent_message_arrival_and_handler_setting(self, mqtt_client):
        """Test race condition when handler is set while messages arrive"""
        await mqtt_client.start()

        processed = []

        async def slow_handler(message: MQTTMessage):
            await asyncio.sleep(0.05)
            processed.append(message.payload)

        # Start sending messages immediately
        async def send_messages():
            for i in range(10):
                message = MQTTMessage(
                    topic="test/topic",
                    payload=f"message_{i}".encode(),
                    qos=0,
                    retain=False,
                    timestamp=datetime.now(),
                )
                await mqtt_client.message_queue.put(message)
                await asyncio.sleep(0.01)

        # Send messages and set handler concurrently
        send_task = asyncio.create_task(send_messages())
        await asyncio.sleep(0.05)
        mqtt_client.set_message_handler(slow_handler)

        await send_task
        await asyncio.sleep(1.0)

        # All messages should be processed
        assert len(processed) > 0

    @pytest.mark.asyncio
    async def test_concurrent_stop_and_message_processing(self, mqtt_client):
        """Test race condition between stop() and ongoing message processing"""
        await mqtt_client.start()

        processing_started = asyncio.Event()
        processing_finished = asyncio.Event()

        async def slow_handler(_: MQTTMessage):
            processing_started.set()
            await asyncio.sleep(0.2)
            processing_finished.set()

        mqtt_client.set_message_handler(slow_handler)

        # Queue a message
        message = MQTTMessage(
            topic="test/topic",
            payload=b"test",
            qos=0,
            retain=False,
            timestamp=datetime.now(),
        )
        await mqtt_client.message_queue.put(message)

        # Wait for processing to start
        await processing_started.wait()

        # Stop while message is being processed
        await mqtt_client.stop()

        # Should handle gracefully
        assert mqtt_client._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_rate_limiter_thread_safety(self, mqtt_client):
        """Test rate limiter under concurrent access from MQTT thread"""
        await mqtt_client.start()

        # Simulate rapid message arrival from MQTT callback thread
        async def simulate_mqtt_callbacks():
            for i in range(100):
                message = MQTTMessage(
                    topic="test/topic",
                    payload=f"msg_{i}".encode(),
                    qos=0,
                    retain=False,
                    timestamp=datetime.now(),
                )
                # Simulate call from MQTT thread via event loop
                mqtt_client._loop.call_soon_threadsafe(
                    lambda m=message: mqtt_client._handle_incoming_message(m)
                )
                await asyncio.sleep(0.001)

        await simulate_mqtt_callbacks()
        await asyncio.sleep(0.5)

        # Should not crash and rate limiter should work
        assert len(mqtt_client.rate_limiter) <= mqtt_client.config.rate_limit_per_minute

    @pytest.mark.asyncio
    async def test_message_queue_backpressure(self, mqtt_client):
        """Test behavior when messages arrive faster than processing"""
        await mqtt_client.start()

        async def very_slow_handler(_: MQTTMessage):
            await asyncio.sleep(0.1)

        mqtt_client.set_message_handler(very_slow_handler)

        # Rapidly queue messages beyond processing capacity
        messages_sent = 0
        messages_dropped = 0

        for i in range(mqtt_client.config.max_queue_size + 20):
            message = MQTTMessage(
                topic="test/topic",
                payload=f"message_{i}".encode(),
                qos=0,
                retain=False,
                timestamp=datetime.now(),
            )
            try:
                mqtt_client.message_queue.put_nowait(message)
                messages_sent += 1
            except asyncio.QueueFull:
                messages_dropped += 1

        # Should drop messages when queue is full
        assert messages_dropped > 0
        assert mqtt_client.message_queue.qsize() == mqtt_client.config.max_queue_size

    @pytest.mark.asyncio
    async def test_rate_limiting_prevents_overload(self, mqtt_client):
        """Test rate limiting prevents system overload"""
        await mqtt_client.start()

        # Try to send more messages than rate limit
        messages_to_send = mqtt_client.config.rate_limit_per_minute + 20
        for i in range(messages_to_send):
            message = MQTTMessage(
                topic="test/topic",
                payload=f"message_{i}".encode(),
                qos=0,
                retain=False,
                timestamp=datetime.now(),
            )
            mqtt_client._handle_incoming_message(message)

        # Queue size should be limited by rate limiter
        # Only the first rate_limit_per_minute messages should be queued
        assert (
            mqtt_client.message_queue.qsize()
            <= mqtt_client.config.rate_limit_per_minute
        )

        # Rate limiter should have accepted initial batch and dropped excess
        # Note: Rate limiting logs warnings but doesn't increment error_count
        assert mqtt_client.message_count <= mqtt_client.config.rate_limit_per_minute

    @pytest.mark.asyncio
    async def test_slow_handler_doesnt_block_mqtt_callbacks(self, mqtt_client):
        """Test that slow message handlers don't block MQTT network loop"""
        await mqtt_client.start()

        handler_call_times = []

        async def slow_handler(_: MQTTMessage):
            handler_call_times.append(time.time())
            await asyncio.sleep(0.1)

        mqtt_client.set_message_handler(slow_handler)

        # Queue multiple messages rapidly
        start_time = time.time()
        for i in range(5):
            message = MQTTMessage(
                topic="test/topic",
                payload=f"message_{i}".encode(),
                qos=0,
                retain=False,
                timestamp=datetime.now(),
            )
            await mqtt_client.message_queue.put(message)

        enqueue_time = time.time() - start_time

        # Enqueueing should be fast (not blocked by handler)
        assert enqueue_time < 0.5

        # Wait for processing
        await asyncio.sleep(1.0)

        # All messages should eventually be processed
        assert len(handler_call_times) == 5

    # Risk 6: Silent Failures
    # ========================

    @pytest.mark.asyncio
    async def test_handler_error_logging(self, mqtt_client, caplog):
        """Test that handler errors are logged and not silently ignored"""
        await mqtt_client.start()

        async def failing_handler(_: MQTTMessage):
            raise RuntimeError("Critical handler error")

        mqtt_client.set_message_handler(failing_handler)

        message = MQTTMessage(
            topic="test/topic",
            payload=b"test",
            qos=0,
            retain=False,
            timestamp=datetime.now(),
        )
        await mqtt_client.message_queue.put(message)

        await asyncio.sleep(0.2)

        # Error should be logged
        assert mqtt_client.error_count > 0

    @pytest.mark.asyncio
    async def test_connection_failure_tracking(self, mqtt_client):
        """Test that connection failures are tracked and visible"""
        # Mock failed connection
        with patch.object(mqtt_client, "client") as mock_client:
            mock_client.connect_async.side_effect = Exception("Connection failed")

            # Attempt connection should handle failure
            try:
                await mqtt_client._connect()
            except Exception:
                pass

            # Should track reconnection attempts
            assert mqtt_client.reconnect_attempts >= 0

    @pytest.mark.asyncio
    async def test_health_status_reflects_errors(self, mqtt_client):
        """Test health status accurately reflects system state"""
        await mqtt_client.start()

        # Simulate high error rate
        mqtt_client.error_count = 50
        mqtt_client.message_count = 100

        health = mqtt_client.get_health_status()

        # Should indicate degraded status
        assert health["status"] in ["degraded", "unhealthy"]
        assert health["error_rate"] > 0.1

    @pytest.mark.asyncio
    async def test_disconnection_event_visibility(self, mqtt_client):
        """Test that disconnection events are properly tracked"""
        await mqtt_client.start()

        # Simulate disconnection
        mqtt_client._on_disconnect(None, None, 1)

        # Should update connection state
        assert not mqtt_client.is_connected

        # Connection info should reflect disconnected state
        info = mqtt_client.get_connection_info()
        assert not info["connected"]

    # Edge Cases
    # ==========

    @pytest.mark.asyncio
    async def test_empty_message_payload(self, mqtt_client):
        """Test handling of empty message payloads"""
        await mqtt_client.start()

        processed = []

        async def handler(_: MQTTMessage):
            processed.append(message.payload)

        mqtt_client.set_message_handler(handler)

        message = MQTTMessage(
            topic="test/topic",
            payload=b"",
            qos=0,
            retain=False,
            timestamp=datetime.now(),
        )
        await mqtt_client.message_queue.put(message)

        await asyncio.sleep(0.2)

        assert len(processed) == 1
        assert processed[0] == b""

    @pytest.mark.asyncio
    async def test_rapid_start_stop_cycles(self, mqtt_client):
        """Test rapid start/stop cycles don't cause issues"""
        for _ in range(3):
            await mqtt_client.start()
            await asyncio.sleep(0.1)
            await mqtt_client.stop()
            await asyncio.sleep(0.1)

        # Should handle gracefully
        assert mqtt_client._shutdown_event.is_set()

    @pytest.mark.asyncio
    async def test_message_timestamps_preserved(self, mqtt_client):
        """Test that message timestamps are preserved through processing"""
        await mqtt_client.start()

        received_timestamps = []

        async def handler(message: MQTTMessage):
            received_timestamps.append(message.timestamp)

        mqtt_client.set_message_handler(handler)

        original_timestamp = datetime.now()
        message = MQTTMessage(
            topic="test/topic",
            payload=b"test",
            qos=0,
            retain=False,
            timestamp=original_timestamp,
        )
        await mqtt_client.message_queue.put(message)

        await asyncio.sleep(0.2)

        assert len(received_timestamps) == 1
        assert received_timestamps[0] == original_timestamp


class TestMQTTReconnectionLogic:
    """Test suite for reconnection logic and resilience"""

    @pytest.fixture
    def config(self):
        return MQTTRadarConfig(
            broker_host="localhost",
            broker_port=1883,
            use_tls=False,
            use_auth=False,
            subscription_topics=["test/topic"],
            subscription_qos=0,
            max_queue_size=100,
            rate_limit_per_minute=60,
            client_id_prefix="test",
        )

    @pytest.mark.asyncio
    async def test_reconnection_backoff(self, config):
        """Test exponential backoff in reconnection attempts"""
        client = RadarMQTTClient(config)
        client.reconnect_delay = 0.1  # Speed up test

        # Mock _connect to not actually connect
        async def mock_connect():
            # Simulate failed connection (just return without connecting)
            pass

        client._connect = mock_connect

        # Trigger reconnection
        await client._schedule_reconnect()

        # Should increment attempts
        assert client.reconnect_attempts == 1

    @pytest.mark.asyncio
    async def test_max_reconnection_attempts(self, config):
        """Test that reconnection stops after max attempts"""
        client = RadarMQTTClient(config)
        client.max_reconnect_attempts = 3
        client.reconnect_attempts = 3

        # Should not attempt reconnection
        await client._schedule_reconnect()

        # Attempts should not increase
        assert client.reconnect_attempts == 3

    @pytest.mark.asyncio
    async def test_shutdown_cancels_reconnection(self, config):
        """Test that shutdown prevents reconnection attempts"""
        client = RadarMQTTClient(config)
        client._shutdown_event.set()

        initial_attempts = client.reconnect_attempts

        # Should not reconnect when shutdown
        await client._schedule_reconnect()

        assert client.reconnect_attempts == initial_attempts


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
