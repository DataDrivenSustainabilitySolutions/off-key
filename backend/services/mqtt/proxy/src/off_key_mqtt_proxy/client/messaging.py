"""
MQTT Message Handler

Handles all incoming MQTT message processing including parsing, callback
management, message queuing, and thread-safe async coordination.
"""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime

import paho.mqtt.client as mqtt
from off_key_core.config.logs import logger

from .models import MQTTMessage


class MessageHandler:
    """
    Manages MQTT message processing and callbacks

    Handles message parsing, user callback coordination (sync/async),
    message queuing, and thread-safe event loop operations.
    """

    def __init__(self, max_queue_size: int = 10000, max_concurrent_handlers: int = 100):
        self.max_queue_size = max_queue_size
        self.max_concurrent_handlers = max_concurrent_handlers

        # Message handling
        self.message_handler: (
            Callable[[MQTTMessage], None]
            | Callable[[MQTTMessage], Awaitable[None]]
            | None
        ) = None
        self.message_queue: list[MQTTMessage] = []
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._handler_queue: (
            asyncio.Queue[tuple[MQTTMessage, Callable[[MQTTMessage], Awaitable[None]]]]
            | None
        ) = None
        self._handler_workers: list[asyncio.Task] = []

        # Metrics
        self.messages_received = 0
        self.last_message_time: datetime | None = None
        self.handler_errors = 0
        self.futures_created = 0
        self.futures_completed = 0
        self.futures_failed = 0
        self.handler_messages_dropped = 0

    def set_client(self, client: mqtt.Client) -> None:
        """Set the MQTT client and register message callback"""
        self.client = client
        self.client.on_message = self._on_message

    def set_handler(
        self,
        handler: Callable[[MQTTMessage], None]
        | Callable[[MQTTMessage], Awaitable[None]],
        event_loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        """
        Set message handler callback

        Args:
            handler: Sync or async message handler function
            event_loop: Event loop for async handlers (uses current if None)
        """
        self.message_handler = handler

        # Store event loop for async handlers
        if event_loop:
            self._event_loop = event_loop
        elif asyncio.iscoroutinefunction(handler):
            try:
                self._event_loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.warning("No event loop available for async message handler")

        # Initialize semaphore for async handlers to limit concurrency
        if asyncio.iscoroutinefunction(handler) and self._event_loop:
            self._ensure_async_workers()

    def clear_handler(self) -> None:
        """Clear the current message handler"""
        self.message_handler = None
        self._event_loop = None

    async def stop(
        self,
        *,
        drain: bool = True,
        timeout_seconds: float | None = None,
    ) -> None:
        """Stop async handler workers after optionally draining queued work."""
        if drain and self._handler_queue:
            try:
                await asyncio.wait_for(
                    self._handler_queue.join(), timeout=timeout_seconds
                )
            except TimeoutError:
                logger.error(
                    "Timed out draining async message handler queue; "
                    "dropping %s queued messages",
                    self._handler_queue.qsize(),
                )
        for task in self._handler_workers:
            task.cancel()
        for task in self._handler_workers:
            with suppress(asyncio.CancelledError):
                await task
        self._handler_workers.clear()
        if self._handler_queue:
            while not self._handler_queue.empty():
                with suppress(asyncio.QueueEmpty):
                    self._handler_queue.get_nowait()
                    self._handler_queue.task_done()
        self._handler_queue = None
        self.message_handler = None
        self._event_loop = None

    def get_queued_messages(self, count: int | None = None) -> list[MQTTMessage]:
        """
        Get messages from the queue

        Args:
            count: Number of messages to retrieve (all if None)

        Returns:
            List of queued messages
        """
        if count is None:
            messages = self.message_queue.copy()
            self.message_queue.clear()
        else:
            messages = self.message_queue[:count]
            self.message_queue = self.message_queue[count:]

        return messages

    def get_queue_size(self) -> int:
        """Get current message queue size"""
        return len(self.message_queue)

    def clear_queue(self) -> None:
        """Clear all queued messages"""
        self.message_queue.clear()

    def get_metrics(self) -> dict:
        """Get message handling metrics"""
        return {
            "messages_received": self.messages_received,
            "queue_size": len(self.message_queue),
            "max_queue_size": self.max_queue_size,
            "last_message_time": (
                self.last_message_time.isoformat() if self.last_message_time else None
            ),
            "has_handler": self.message_handler is not None,
            "handler_errors": self.handler_errors,
            "futures_created": self.futures_created,
            "futures_completed": self.futures_completed,
            "futures_failed": self.futures_failed,
            "handler_queue_size": (
                self._handler_queue.qsize() if self._handler_queue else 0
            ),
            "handler_messages_dropped": self.handler_messages_dropped,
        }

    def get_message_rate(self, connection_start_time: datetime | None = None) -> float:
        """
        Calculate message rate since connection started

        Args:
            connection_start_time: When connection was established

        Returns:
            Messages per second
        """
        if not connection_start_time or not self.last_message_time:
            return 0.0

        duration = (datetime.now() - connection_start_time).total_seconds()
        if duration <= 0:
            return 0.0

        return self.messages_received / duration

    def _on_message(self, client, userdata, msg):
        """MQTT message callback - processes incoming messages"""
        try:
            message = MQTTMessage.from_mqtt_message(msg)
            self.messages_received += 1
            self.last_message_time = message.timestamp

            logger.debug(f"Received message from {msg.topic}: {len(msg.payload)} bytes")

            # Handle message with user callback
            if self.message_handler:
                self._handle_user_callback(message)
            else:
                # Queue message if no handler
                self._queue_message(message)

        except Exception as e:
            logger.error(f"Error processing MQTT message: {e}")

    def _ensure_async_workers(self) -> None:
        """Ensure a bounded queue and fixed worker pool exist for async handlers."""
        if not self._event_loop or self._event_loop.is_closed():
            return
        if self._handler_queue is None:
            self._handler_queue = asyncio.Queue(maxsize=self.max_queue_size)
        self._handler_workers = [
            task for task in self._handler_workers if not task.done()
        ]
        missing_workers = self.max_concurrent_handlers - len(self._handler_workers)
        for _ in range(max(missing_workers, 0)):
            self._handler_workers.append(
                self._event_loop.create_task(self._async_handler_worker())
            )

    async def _async_handler_worker(self) -> None:
        """Process queued async message handler work with bounded concurrency."""
        assert self._handler_queue is not None
        while True:
            message, handler = await self._handler_queue.get()
            try:
                await handler(message)
                self.futures_completed += 1
            except Exception as e:
                self.futures_failed += 1
                self.handler_errors += 1
                logger.error(f"Exception in async message handler: {e}", exc_info=True)
            finally:
                self._handler_queue.task_done()

    def _handle_user_callback(self, message: MQTTMessage) -> None:
        """Handle user-provided message callback (sync or async)"""
        try:
            if asyncio.iscoroutinefunction(self.message_handler):
                # Handle async callback
                if self._event_loop and not self._event_loop.is_closed():
                    try:
                        handler = self.message_handler
                        self._event_loop.call_soon_threadsafe(
                            self._enqueue_async_handler_work,
                            message,
                            handler,
                        )
                    except RuntimeError as e:
                        # Event loop closed between check and call (race condition)
                        logger.error(f"Event loop closed during callback: {e}")
                        self.handler_errors += 1
                else:
                    logger.error("Event loop not available for async message handler")
            else:
                # Handle sync callback directly
                self.message_handler(message)

        except Exception as e:
            self.handler_errors += 1
            logger.error(f"Error in user message handler: {e}")

    def _enqueue_async_handler_work(
        self,
        message: MQTTMessage,
        handler: Callable[[MQTTMessage], Awaitable[None]],
    ) -> None:
        """Enqueue async handler work on the event loop thread without blocking MQTT."""
        if self._handler_queue is None:
            self._ensure_async_workers()
        if self._handler_queue is None:
            self.handler_errors += 1
            logger.error("Async handler queue is not available")
            return

        try:
            self._handler_queue.put_nowait((message, handler))
            self.futures_created += 1
        except asyncio.QueueFull:
            self.handler_messages_dropped += 1
            self.handler_errors += 1
            logger.warning(
                "Async message handler queue full (%s), dropping message from %s",
                self.max_queue_size,
                message.topic,
            )

    def _queue_message(self, message: MQTTMessage) -> None:
        """Queue message when no handler is available"""
        if len(self.message_queue) < self.max_queue_size:
            self.message_queue.append(message)
            logger.debug(f"Queued message from {message.topic}")
        else:
            logger.warning(
                f"Message queue full ({self.max_queue_size}), "
                f"dropping message from {message.topic}"
            )
