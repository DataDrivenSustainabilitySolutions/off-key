"""
MQTT Message Handler

Parses incoming MQTT messages on Paho's network thread and hands them to one
synchronous callback.
"""

from collections.abc import Callable

import paho.mqtt.client as mqtt
from off_key_core.config.logs import logger
from off_key_core.schemas.collection_wire import MAX_ENVELOPE_BYTES

from .models import MQTTMessage


class MessageHandler:
    """Route parsed messages to a synchronous, thread-safe callback.

    The collector's CollectionBuffer.receive takes its own lock, so the
    callback runs inline on the network thread without an event loop hop.
    """

    def __init__(self):
        self.message_handler: Callable[[MQTTMessage], None] | None = None

    def set_client(self, client: mqtt.Client) -> None:
        """Set the MQTT client and register message callback"""
        self.client = client
        self.client.on_message = self._on_message

    def set_handler(self, handler: Callable[[MQTTMessage], None]) -> None:
        self.message_handler = handler

    def _on_message(self, client, userdata, msg):
        """MQTT message callback - processes incoming messages"""
        try:
            # Admit every envelope TACTIC can produce; the payload decoder then
            # enforces the upstream payload limit itself.
            if len(msg.payload) > MAX_ENVELOPE_BYTES:
                return
            message = MQTTMessage.from_mqtt_message(msg)

            logger.debug(
                "Received message from %s: %s bytes", msg.topic, len(msg.payload)
            )

            handler = self.message_handler
            if handler is None:
                return
            try:
                handler(message)
            except Exception as e:
                logger.error(f"Error in user message handler: {e}")

        except Exception as e:
            logger.error(f"Error processing MQTT message: {e}")
