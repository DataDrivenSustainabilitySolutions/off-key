"""
MQTT Client Facade

High-level MQTT client that orchestrates connection management, subscriptions,
and message handling through dedicated components. Provides a clean, simple
API while delegating responsibilities to specialized managers.
"""

import json
from datetime import datetime
from typing import Optional, Dict, Any, Callable, Union, Awaitable

import paho.mqtt.client as mqtt
from off_key_core.config.logs import logger
from off_key_core.utils.enum import HealthStatus
from ..config.config import MQTTConfig
from ..auth import ApiKeyAuthHandler
from .models import (
    ConnectionState,
    MQTTMessage,
    ClientConnectionInfo,
    ClientHealthStatus,
)
from .connection import ConnectionManager
from .subscriptions import SubscriptionManager
from .messaging import MessageHandler


class MQTTClient:
    """
    MQTT Client Facade

    Orchestrates MQTT operations through specialized components:
    - ConnectionManager: Handles connection lifecycle
    - SubscriptionManager: Manages topic subscriptions
    - MessageHandler: Processes incoming messages

    Provides a unified, clean API while maintaining separation of concerns.
    """

    def __init__(
        self, config: MQTTConfig, auth_handler: Optional[ApiKeyAuthHandler] = None
    ):
        self.config = config
        self.auth_handler = auth_handler

        # Initialize component managers
        self.connection_manager = ConnectionManager(
            config,
            auth_handler,
            on_connected=self._on_connected,
            on_disconnected=self._on_disconnected,
        )

        self.subscription_manager = SubscriptionManager(
            default_qos=config.subscription_qos
        )

        self.message_handler = MessageHandler(
            max_queue_size=config.max_message_queue_size
        )

        # Track messages sent for metrics
        self.messages_sent = 0

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.disconnect()

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
        handler: Union[
            Callable[[MQTTMessage], None], Callable[[MQTTMessage], Awaitable[None]]
        ],
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
        success = await self.connection_manager.connect()

        if success:
            # Wire up the components after successful connection
            client = self.connection_manager.client
            self.subscription_manager.set_client(client)
            self.message_handler.set_client(client)

        return success

    async def disconnect(self) -> None:
        """Disconnect from MQTT broker"""
        await self.connection_manager.disconnect()

    async def stop(self) -> None:
        """Stop MQTT client (implements Stoppable protocol)"""
        await self.disconnect()

    async def subscribe(self, topic: str, qos: Optional[int] = None) -> bool:
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
        self, topic: str, payload: Dict[str, Any], qos: int = 0, retain: bool = False
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
                self.messages_sent += 1
                logger.debug(f"Published message to {topic}")
                return True
            else:
                logger.error(f"Failed to publish to {topic}: {result.rc}")
                return False

        except Exception as e:
            logger.error(f"Error publishing to {topic}: {e}")
            return False

    def get_connection_info(self) -> ClientConnectionInfo:
        """Get current connection information"""
        base_info = self.connection_manager.get_connection_info()

        return ClientConnectionInfo(
            state=base_info["state"],
            broker_host=base_info["broker_host"],
            broker_port=base_info["broker_port"],
            client_id=base_info["client_id"],
            connection_start_time=base_info["connection_start_time"],
            reconnect_attempts=base_info["reconnect_attempts"],
            subscriptions=list(self.subscription_manager.get_subscriptions()),
            pending_subscriptions=list(
                self.subscription_manager.get_pending_subscriptions()
            ),
            messages_sent=self.messages_sent,
        )

    def get_health_status(self) -> ClientHealthStatus:
        """Get health status for monitoring"""
        # Get metrics from components
        connection_info = self.connection_manager.get_connection_info()
        message_metrics = self.message_handler.get_metrics()

        # Calculate derived metrics
        uptime_seconds = self.connection_manager.get_uptime_seconds()
        message_rate = self.message_handler.get_message_rate(
            self.connection_manager.connection_start_time
        )

        return ClientHealthStatus(
            status=(
                HealthStatus.HEALTHY
                if self.state == ConnectionState.CONNECTED
                else HealthStatus.UNHEALTHY
            ),
            state=self.state.value,
            uptime_seconds=uptime_seconds,
            messages_received=message_metrics["messages_received"],
            messages_sent=self.messages_sent,
            message_rate=round(message_rate, 2),
            active_subscriptions=self.subscription_manager.get_subscription_count(),
            reconnect_attempts=connection_info["reconnect_attempts"],
            queue_size=message_metrics["queue_size"],
            last_message_time=message_metrics["last_message_time"],
            last_message_age_seconds=(
                (
                    datetime.now() - self.message_handler.last_message_time
                ).total_seconds()
                if self.message_handler.last_message_time
                else None
            ),
        )

    def get_queued_messages(self, count: Optional[int] = None):
        """Get messages from the message queue"""
        return self.message_handler.get_queued_messages(count)

    def clear_message_queue(self) -> None:
        """Clear all queued messages"""
        self.message_handler.clear_queue()

    async def _on_connected(self) -> None:
        """Called when connection is established"""
        # Resubscribe to all topics
        await self.subscription_manager.resubscribe_all()

    async def _on_disconnected(self, unexpected: bool) -> None:
        """Called when connection is lost"""
        # Could add additional cleanup logic here if needed
        pass
