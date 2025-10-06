"""
MQTT Subscription Manager

Manages all MQTT topic subscriptions including active subscriptions,
pending subscriptions, and resubscription after reconnection.
"""

from typing import Set, Optional

import paho.mqtt.client as mqtt
from off_key_core.config.logs import logger


class SubscriptionManager:
    """
    Manages MQTT topic subscriptions

    Tracks active and pending subscriptions, handles subscribe/unsubscribe
    operations, and ensures topics are resubscribed after reconnection.
    """

    def __init__(self, default_qos: int = 1):
        self.default_qos = default_qos

        # Subscription tracking
        self.subscriptions: Set[str] = set()
        self.pending_subscriptions: Set[str] = set()

    def set_client(self, client: mqtt.Client) -> None:
        """Set the MQTT client and register callbacks"""
        self.client = client
        self.client.on_subscribe = self._on_subscribe
        self.client.on_unsubscribe = self._on_unsubscribe

    async def subscribe(self, topic: str, qos: Optional[int] = None) -> bool:
        """
        Subscribe to MQTT topic

        Args:
            topic: MQTT topic to subscribe to
            qos: Quality of Service level (uses default if None)

        Returns:
            True if subscription successful, False otherwise
        """
        if qos is None:
            qos = self.default_qos

        logger.info(f"Subscribing to topic: {topic} (QoS: {qos})")

        if not hasattr(self, "client") or not self.client:
            logger.warning(f"Cannot subscribe to {topic}: no client available")
            self.pending_subscriptions.add(topic)
            return False

        try:
            result, mid = self.client.subscribe(topic, qos)

            if result == mqtt.MQTT_ERR_SUCCESS:
                self.subscriptions.add(topic)
                # Remove from pending if it was there
                self.pending_subscriptions.discard(topic)
                logger.info(f"Successfully subscribed to {topic}")
                return True
            else:
                error_msg = self._get_subscription_error_message(result)
                logger.error(f"Failed to subscribe to {topic}: {result} - {error_msg}")
                # Add to pending for retry
                self.pending_subscriptions.add(topic)
                return False

        except Exception as e:
            logger.error(f"Error subscribing to {topic}: {e}")
            self.pending_subscriptions.add(topic)
            return False

    async def unsubscribe(self, topic: str) -> bool:
        """
        Unsubscribe from MQTT topic

        Args:
            topic: MQTT topic to unsubscribe from

        Returns:
            True if unsubscription successful, False otherwise
        """
        logger.info(f"Unsubscribing from topic: {topic}")

        if not hasattr(self, "client") or not self.client:
            logger.warning(f"Cannot unsubscribe from {topic}: no client available")
            return False

        try:
            result, mid = self.client.unsubscribe(topic)

            if result == mqtt.MQTT_ERR_SUCCESS:
                self.subscriptions.discard(topic)
                self.pending_subscriptions.discard(topic)
                logger.info(f"Successfully unsubscribed from {topic}")
                return True
            else:
                logger.error(f"Failed to unsubscribe from {topic}: {result}")
                return False

        except Exception as e:
            logger.error(f"Error unsubscribing from {topic}: {e}")
            return False

    async def resubscribe_all(self) -> None:
        """Resubscribe to all topics after reconnection"""
        topics_to_resubscribe = self.subscriptions.copy()
        topics_to_resubscribe.update(self.pending_subscriptions)

        if not topics_to_resubscribe:
            return

        logger.info(f"Resubscribing to {len(topics_to_resubscribe)} topics")

        for topic in topics_to_resubscribe:
            await self.subscribe(topic)

        # Clear pending after attempting to resubscribe
        self.pending_subscriptions.clear()

    def get_subscriptions(self) -> Set[str]:
        """Get current active subscriptions"""
        return self.subscriptions.copy()

    def get_pending_subscriptions(self) -> Set[str]:
        """Get pending subscriptions"""
        return self.pending_subscriptions.copy()

    def get_all_topics(self) -> Set[str]:
        """Get all topics (active + pending)"""
        return self.subscriptions.union(self.pending_subscriptions)

    def get_subscription_count(self) -> int:
        """Get number of active subscriptions"""
        return len(self.subscriptions)

    def clear_all(self) -> None:
        """Clear all subscription tracking"""
        self.subscriptions.clear()
        self.pending_subscriptions.clear()

    def _on_subscribe(self, client, userdata, mid, granted_qos):
        """MQTT subscription callback"""
        logger.debug(f"Subscription confirmed with QoS: {granted_qos}")

    def _on_unsubscribe(self, client, userdata, mid):
        """MQTT unsubscription callback"""
        logger.debug("Unsubscription confirmed")

    def _get_subscription_error_message(self, rc: int) -> str:
        """Get human-readable subscription error message"""
        error_messages = {
            1: "Out of memory",
            2: "Invalid parameter",
            3: "No connection to broker",
            4: "Connection refused - bad username/password (check API key)",
            5: "Connection refused - not authorized",
            6: "Connection refused - server unavailable",
            7: "Connection lost",
        }

        return error_messages.get(rc, f"Unknown subscription error code {rc}")
