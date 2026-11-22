"""
MQTT Client Facade

High-level MQTT client that orchestrates connection management, subscriptions,
and message handling through dedicated components. Provides a clean, simple
API while delegating responsibilities to specialized managers.
"""

from collections.abc import Callable

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

        self.message_handler = MessageHandler()

    @property
    def state(self) -> ConnectionState:
        """Get current connection state"""
        return self.connection_manager.state

    @property
    def is_connected(self) -> bool:
        """Check if currently connected"""
        return self.connection_manager.is_connected

    def set_message_handler(self, handler: Callable[[MQTTMessage], None]) -> None:
        """Route received messages to a synchronous, thread-safe callback."""
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

    async def subscribe(self, topic: str) -> bool:
        """
        Subscribe to MQTT topic at QoS 0

        Args:
            topic: MQTT topic to subscribe to

        Returns:
            True if subscription successful, False otherwise
        """
        if not self.is_connected:
            logger.warning(f"Cannot subscribe to {topic}: not connected")
            return False

        return await self.subscription_manager.subscribe(topic)

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

    async def _on_connected(self) -> None:
        """Called when connection is established"""
        client = self.connection_manager.client
        if client is None:
            raise RuntimeError("MQTT connected without a client")
        self.subscription_manager.set_client(client)
        self.message_handler.set_client(client)
        # The collection loop restores the current catalog after a reconnect.
