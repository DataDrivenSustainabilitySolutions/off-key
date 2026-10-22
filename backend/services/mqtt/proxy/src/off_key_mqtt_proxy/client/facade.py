"""
MQTT Client Facade

High-level MQTT client that orchestrates connection management, subscriptions,
and message handling through dedicated components. Provides a clean, simple
API while delegating responsibilities to specialized managers.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import paho.mqtt.client as mqtt
from off_key_core.config.logs import logger

from ..config.config import MQTTConfig
from .connection import ConnectionManager
from .messaging import MessageHandler
from .models import ConnectionState, MQTTMessage
from .subscriptions import SubscriptionManager


class MQTTClient:
    """
    MQTT Client Facade

    Orchestrates MQTT operations through specialized components:
    - ConnectionManager: Handles connection lifecycle
    - SubscriptionManager: Manages topic subscriptions
    - MessageHandler: Processes incoming messages

    Provides a unified, clean API while maintaining separation of concerns.
    """

    def __init__(self, config: MQTTConfig):
        self.config = config

        # Initialize component managers
        self.connection_manager = ConnectionManager(
            config, on_connected=self._on_connected
        )

        self.subscription_manager = SubscriptionManager()

        self.message_handler = MessageHandler(
            max_queue_size=config.max_message_queue_size
        )

        self._pending_publishes: list[mqtt.MQTTMessageInfo] = []

    @property
    def state(self) -> ConnectionState:
        """Get current connection state"""
        return self.connection_manager.state

    @property
    def is_connected(self) -> bool:
        """Check if currently connected"""
        return self.connection_manager.is_connected

    def set_message_handler(
        self,
        handler: Callable[[MQTTMessage], None]
        | Callable[[MQTTMessage], Awaitable[None]],
    ) -> None:
        """
        Set message handler callback

        Args:
            handler: Sync or async message handler function
        """
        self.message_handler.set_handler(handler)

    async def connect(self) -> bool:
        """
        Connect to MQTT broker

        Returns:
            True if connection successful, False otherwise
        """
        return await self.connection_manager.connect()

    async def disconnect(self) -> None:
        """Disconnect from MQTT broker"""
        await self.connection_manager.disconnect()
        await self.message_handler.stop(
            drain=True,
            timeout_seconds=self.config.graceful_shutdown_timeout,
        )

    async def subscribe(self, topic: str, qos: int | None = None) -> bool:
        """
        Subscribe to MQTT topic

        Args:
            topic: MQTT topic to subscribe to
            qos: Quality of Service level

        Returns:
            True if subscription successful, False otherwise
        """
        if not self.is_connected:
            logger.warning(f"Cannot subscribe to {topic}: not connected")
            return False

        return await self.subscription_manager.subscribe(topic, qos)

    async def unsubscribe(self, topic: str) -> bool:
        """
        Unsubscribe from MQTT topic

        Args:
            topic: MQTT topic to unsubscribe from

        Returns:
            True if unsubscription successful, False otherwise
        """
        if not self.is_connected:
            logger.warning(f"Cannot unsubscribe from {topic}: not connected")
            return False

        return await self.subscription_manager.unsubscribe(topic)

    async def publish(
        self, topic: str, payload: dict[str, Any], qos: int = 0, retain: bool = False
    ) -> bool:
        """
        Publish message to MQTT topic

        Args:
            topic: MQTT topic to publish to
            payload: Message payload dictionary
            qos: Quality of Service level
            retain: Retain message flag

        Returns:
            True if publish successful, False otherwise
        """
        if not self.is_connected:
            logger.warning(f"Cannot publish to {topic}: not connected")
            return False

        client = self.connection_manager.client
        if not client:
            logger.error("No MQTT client available for publishing")
            return False

        try:
            payload_json = json.dumps(payload)
            result = client.publish(topic, payload_json, qos, retain)

            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                if qos:
                    self._pending_publishes = [
                        item
                        for item in self._pending_publishes
                        if not item.is_published()
                    ]
                    self._pending_publishes.append(result)
                logger.debug(f"Published message to {topic}")
                return True
            logger.error(f"Failed to publish to {topic}: {result.rc}")
            return False

        except Exception as e:
            logger.error(f"Error publishing to {topic}: {e}")
            return False

    async def drain_publishes(self) -> None:
        while self._pending_publishes:
            self._pending_publishes = [
                info for info in self._pending_publishes if not info.is_published()
            ]
            if self._pending_publishes:
                await asyncio.sleep(0.05)

    async def _on_connected(self) -> None:
        """Called when connection is established"""
        client = self.connection_manager.client
        if client is None:
            raise RuntimeError("MQTT connected without a client")
        self._pending_publishes.clear()
        self.subscription_manager.set_client(client)
        self.message_handler.set_client(client)
        # The collection loop restores the current catalog after a reconnect.
