"""
MQTT Message Handler

Handles all incoming MQTT message processing including parsing, callback
management, message queuing, and thread-safe async coordination.
"""

import asyncio
from datetime import datetime
from typing import Optional, Callable, List, Union, Awaitable

import paho.mqtt.client as mqtt
from ....core.logs import logger
from .models import MQTTMessage


class MessageHandler:
    """
    Manages MQTT message processing and callbacks

    Handles message parsing, user callback coordination (sync/async),
    message queuing, and thread-safe event loop operations.
    """

    def __init__(self, max_queue_size: int = 10000):
        self.max_queue_size = max_queue_size

        # Message handling
        self.message_handler: Optional[
            Union[
                Callable[[MQTTMessage], None], Callable[[MQTTMessage], Awaitable[None]]
            ]
        ] = None
        self.message_queue: List[MQTTMessage] = []
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

        # Metrics
        self.messages_received = 0
        self.last_message_time: Optional[datetime] = None

    def set_client(self, client: mqtt.Client) -> None:
        """Set the MQTT client and register message callback"""
        self.client = client
        self.client.on_message = self._on_message

    def set_handler(
        self,
        handler: Union[
            Callable[[MQTTMessage], None], Callable[[MQTTMessage], Awaitable[None]]
        ],
        event_loop: Optional[asyncio.AbstractEventLoop] = None,
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

    def clear_handler(self) -> None:
        """Clear the current message handler"""
        self.message_handler = None
        self._event_loop = None

    def get_queued_messages(self, count: Optional[int] = None) -> List[MQTTMessage]:
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
        }

    def get_message_rate(
        self, connection_start_time: Optional[datetime] = None
    ) -> float:
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

    def _handle_user_callback(self, message: MQTTMessage) -> None:
        """Handle user-provided message callback (sync or async)"""
        try:
            if asyncio.iscoroutinefunction(self.message_handler):
                # Handle async callback
                if self._event_loop and not self._event_loop.is_closed():
                    # Schedule in main event loop thread-safely
                    _future = asyncio.run_coroutine_threadsafe(
                        self.message_handler(message), self._event_loop
                    )
                    # Don't wait for completion to avoid blocking MQTT thread
                else:
                    logger.error("Event loop not available for async message handler")
            else:
                # Handle sync callback directly
                self.message_handler(message)

        except Exception as e:
            logger.error(f"Error in user message handler: {e}")

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