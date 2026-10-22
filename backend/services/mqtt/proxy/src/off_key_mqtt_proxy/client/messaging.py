"""
MQTT Message Handler

Parses incoming MQTT messages on Paho's network thread and hands them to one
synchronous callback, or queues a bounded number while none is set.
"""

from collections.abc import Callable
from datetime import datetime

import paho.mqtt.client as mqtt
from off_key_core.config.logs import logger
from off_key_core.schemas.collection_wire import MAX_ENVELOPE_BYTES

from .models import MQTTMessage


class MessageHandler:
    """Route parsed messages to a synchronous, thread-safe callback.

    The collector's CollectionBuffer.receive takes its own lock, so the
    callback runs inline on the network thread without an event loop hop.
    """

    def __init__(self, max_queue_size: int = 10000):
        self.max_queue_size = max_queue_size
        self.message_handler: Callable[[MQTTMessage], None] | None = None
        self.message_queue: list[MQTTMessage] = []

        # Metrics
        self.messages_received = 0
        self.last_message_time: datetime | None = None
        self.handler_errors = 0
        self.handler_messages_dropped = 0

    def set_client(self, client: mqtt.Client) -> None:
        """Set the MQTT client and register message callback"""
        self.client = client
        self.client.on_message = self._on_message

    def set_handler(self, handler: Callable[[MQTTMessage], None]) -> None:
        self.message_handler = handler

    def clear_handler(self) -> None:
        self.message_handler = None

    def get_queue_size(self) -> int:
        """Get current message queue size"""
        return len(self.message_queue)

    def _on_message(self, client, userdata, msg):
        """MQTT message callback - processes incoming messages"""
        try:
            # Admit every envelope TACTIC can produce; the payload decoder then
            # enforces the upstream payload limit itself.
            if len(msg.payload) > MAX_ENVELOPE_BYTES:
                self.handler_messages_dropped += 1
                return
            message = MQTTMessage.from_mqtt_message(msg)
            self.messages_received += 1
            self.last_message_time = message.timestamp

            logger.debug(f"Received message from {msg.topic}: {len(msg.payload)} bytes")

            handler = self.message_handler
            if handler is None:
                self._queue_message(message)
                return
            try:
                handler(message)
            except Exception as e:
                self.handler_errors += 1
                logger.error(f"Error in user message handler: {e}")

        except Exception as e:
            logger.error(f"Error processing MQTT message: {e}")

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
