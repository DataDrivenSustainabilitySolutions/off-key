"""
MQTT Client with WebSocket/TLS Support for Pionix Cloud

High-performance MQTT client with WebSocket transport, TLS encryption,
automatic reconnection, and comprehensive error handling.
"""

import asyncio
import json
import ssl
from datetime import datetime
from typing import Optional, Dict, Any, Callable, List, Set, Awaitable, Union
from dataclasses import dataclass
from enum import Enum

import paho.mqtt.client as mqtt
from ...core.logs import logger
from .config import MQTTConfig
from .auth import ApiKeyAuthHandler, ApiKeyAuthError


class ConnectionState(Enum):
    """MQTT connection states"""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


@dataclass
class MQTTMessage:
    """MQTT message data structure"""

    topic: str
    payload: Dict[str, Any]
    timestamp: datetime
    qos: int
    retain: bool

    @classmethod
    def from_mqtt_message(cls, msg: mqtt.MQTTMessage) -> "MQTTMessage":
        """Create MQTTMessage from paho MQTT message"""
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"Failed to decode message payload: {e}")
            payload = {"raw": msg.payload.decode(errors="ignore")}

        return cls(
            topic=msg.topic,
            payload=payload,
            timestamp=datetime.now(),
            qos=msg.qos,
            retain=msg.retain,
        )


class MQTTClientError(Exception):
    """MQTT client error"""

    pass


class MQTTClient:
    """
    Advanced MQTT client for Pionix Cloud with WebSocket/TLS support

    Features:
    - WebSocket transport with TLS encryption
    - API-Key based authentication
    - Automatic reconnection with exponential backoff
    - Message queuing during disconnections
    - Comprehensive error handling and logging
    - Performance monitoring
    """

    def __init__(self, config: MQTTConfig, auth_handler: ApiKeyAuthHandler):
        self.config = config
        self.auth_handler = auth_handler

        # Connection state
        self.state = ConnectionState.DISCONNECTED
        self.client: Optional[mqtt.Client] = None
        self.last_connection_attempt = 0
        self.reconnect_attempts = 0

        # Subscriptions
        self.subscriptions: Set[str] = set()
        self.pending_subscriptions: Set[str] = set()

        # Message handling
        self.message_handler: Optional[
            Union[
                Callable[[MQTTMessage], None], Callable[[MQTTMessage], Awaitable[None]]
            ]
        ] = None
        self.message_queue: List[MQTTMessage] = []
        self.max_queue_size = config.max_message_queue_size

        # Performance metrics
        self.messages_received = 0
        self.messages_sent = 0
        self.last_message_time: Optional[datetime] = None
        self.connection_start_time: Optional[datetime] = None

        # Async coordination
        self._connection_event = asyncio.Event()
        self._shutdown_event = asyncio.Event()
        self._reconnect_task: Optional[asyncio.Task] = None
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    def set_message_handler(
        self,
        handler: Union[
            Callable[[MQTTMessage], None], Callable[[MQTTMessage], Awaitable[None]]
        ],
    ):
        """Set message handler callback (sync or async)"""
        self.message_handler = handler

    async def connect(self) -> bool:
        """
        Connect to MQTT broker with Firebase authentication

        Returns:
            True if connection successful, False otherwise
        """
        # Store reference to current event loop for thread-safe operations
        self._event_loop = asyncio.get_running_loop()

        if self.state == ConnectionState.CONNECTED:
            logger.info("MQTT client already connected")
            return True

        self.state = ConnectionState.CONNECTING
        logger.info(
            f"Connecting to MQTT broker at "
            f"{self.config.broker_host}:{self.config.broker_port}"
        )

        try:
            # Get API-Key credentials
            username, password = await self.auth_handler.get_mqtt_credentials()

            # Create MQTT client
            client_id = self.config.get_client_id()
            self.client = mqtt.Client(client_id=client_id, transport="websockets")

            # Configure TLS
            if self.config.use_tls:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE  # For WebSocket connections
                self.client.tls_set_context(context)

            # Set authentication
            self.client.username_pw_set(username, password)

            # Set callbacks
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message
            self.client.on_subscribe = self._on_subscribe
            self.client.on_unsubscribe = self._on_unsubscribe
            self.client.on_log = self._on_log

            # Connect to broker with reduced keep-alive for WebSocket stability
            self.client.connect_async(
                self.config.broker_host,
                self.config.broker_port,
                keepalive=15,  # Reduced from 60 to prevent network infr timeouts
            )

            # Start network loop
            self.client.loop_start()

            # Wait for connection with timeout
            try:
                await asyncio.wait_for(
                    self._connection_event.wait(),
                    timeout=self.config.connection_timeout,
                )

                if self.state == ConnectionState.CONNECTED:
                    logger.info("MQTT connection established successfully")
                    self.connection_start_time = datetime.now()
                    self.reconnect_attempts = 0

                    # Resubscribe to topics
                    await self._resubscribe_topics()

                    return True
                else:
                    logger.error("MQTT connection failed")
                    return False

            except asyncio.TimeoutError:
                logger.error("MQTT connection timeout")
                self.state = ConnectionState.FAILED
                return False

        except ApiKeyAuthError as e:
            logger.error(f"API-Key authentication error: {e}")
            self.state = ConnectionState.FAILED
            return False
        except Exception as e:
            logger.error(f"Unexpected error during MQTT connection: {e}")
            self.state = ConnectionState.FAILED
            return False

    async def stop(self):
        """Stop MQTT client (implements Stoppable protocol)"""
        await self.disconnect()

    async def disconnect(self):
        """Disconnect from MQTT broker"""
        if self.state == ConnectionState.DISCONNECTED:
            return

        logger.info("Disconnecting from MQTT broker")
        self.state = ConnectionState.DISCONNECTED
        self._shutdown_event.set()

        # Cancel reconnect task
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass

        # Disconnect client
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()

        # Clear event loop reference
        self._event_loop = None

        logger.info("MQTT client disconnected")

    async def subscribe(self, topic: str, qos: int = None) -> bool:
        """
        Subscribe to MQTT topic

        Args:
            topic: MQTT topic to subscribe to
            qos: Quality of Service level (uses config default if None)

        Returns:
            True if subscription successful, False otherwise
        """
        if qos is None:
            qos = self.config.subscription_qos

        logger.info(f"Subscribing to topic: {topic} (QoS: {qos})")

        if self.state != ConnectionState.CONNECTED:
            logger.warning(f"Cannot subscribe to {topic}: not connected")
            self.pending_subscriptions.add(topic)
            return False

        try:
            result, mid = self.client.subscribe(topic, qos)

            if result == mqtt.MQTT_ERR_SUCCESS:
                self.subscriptions.add(topic)
                logger.info(f"Successfully subscribed to {topic}")
                return True
            else:
                error_msg = self._get_subscription_error_message(result)
                logger.error(f"Failed to subscribe to {topic}: {result} - {error_msg}")
                return False

        except Exception as e:
            logger.error(f"Error subscribing to {topic}: {e}")
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

        if self.state != ConnectionState.CONNECTED:
            logger.warning(f"Cannot unsubscribe from {topic}: not connected")
            return False

        try:
            result, mid = self.client.unsubscribe(topic)

            if result == mqtt.MQTT_ERR_SUCCESS:
                self.subscriptions.discard(topic)
                logger.info(f"Successfully unsubscribed from {topic}")
                return True
            else:
                logger.error(f"Failed to unsubscribe from {topic}: {result}")
                return False

        except Exception as e:
            logger.error(f"Error unsubscribing from {topic}: {e}")
            return False

    async def publish(
        self, topic: str, payload: Dict[str, Any], qos: int = 0, retain: bool = False
    ) -> bool:
        """
        Publish message to MQTT topic

        Args:
            topic: MQTT topic to publish to
            payload: Message payload
            qos: Quality of Service level
            retain: Retain message flag

        Returns:
            True if publish successful, False otherwise
        """
        if self.state != ConnectionState.CONNECTED:
            logger.warning(f"Cannot publish to {topic}: not connected")
            return False

        try:
            payload_json = json.dumps(payload)
            result = self.client.publish(topic, payload_json, qos, retain)

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

    def _on_connect(self, client, userdata, flags, rc):
        """MQTT connection callback"""
        if rc == 0:
            self.state = ConnectionState.CONNECTED
            logger.info("MQTT broker connection successful")
            self._connection_event.set()
        else:
            self.state = ConnectionState.FAILED
            logger.error(
                f"MQTT connection failed with code {rc}: "
                f"{self._get_connection_error_message(rc)}"
            )
            self._connection_event.set()

    def _on_disconnect(self, client, userdata, rc):
        """MQTT disconnection callback"""
        self.state = ConnectionState.DISCONNECTED
        self._connection_event.clear()

        if rc != 0:
            logger.warning(f"Unexpected MQTT disconnection: {rc}")
            # Start reconnection process
            if not self._shutdown_event.is_set():
                self._schedule_reconnect()
        else:
            logger.info("MQTT disconnection completed")

    def _on_message(self, client, userdata, msg):
        """MQTT message callback"""
        try:
            message = MQTTMessage.from_mqtt_message(msg)
            self.messages_received += 1
            self.last_message_time = message.timestamp

            logger.debug(f"Received message from {msg.topic}: {len(msg.payload)} bytes")

            # Handle message
            if self.message_handler:
                try:
                    if asyncio.iscoroutinefunction(self.message_handler):
                        # Schedule async handler in the main event loop
                        if self._event_loop and not self._event_loop.is_closed():
                            future = asyncio.run_coroutine_threadsafe(  # noqa
                                self.message_handler(message), self._event_loop  # noqa
                            )  # noqa
                            # Don't wait for completion to avoid blocking MQTT thread
                        else:
                            logger.error(
                                "Event loop not available for async message handler"
                            )
                    else:
                        # Handle sync callback normally
                        self.message_handler(message)
                except Exception as e:
                    logger.error(f"Error in message handler: {e}")
            else:
                # Queue message if no handler
                if len(self.message_queue) < self.max_queue_size:
                    self.message_queue.append(message)
                else:
                    logger.warning("Message queue full, dropping message")

        except Exception as e:
            logger.error(f"Error processing MQTT message: {e}")

    def _on_subscribe(self, client, userdata, mid, granted_qos):
        """MQTT subscription callback"""
        logger.debug(f"Subscription confirmed with QoS: {granted_qos}")

    def _on_unsubscribe(self, client, userdata, mid):
        """MQTT unsubscription callback"""
        logger.debug("Unsubscription confirmed")

    def _on_log(self, client, userdata, level, buf):
        """MQTT log callback"""
        if level == mqtt.MQTT_LOG_ERR:
            logger.error(f"MQTT: {buf}")
        elif level == mqtt.MQTT_LOG_WARNING:
            logger.warning(f"MQTT: {buf}")
        else:
            logger.debug(f"MQTT: {buf}")

    def _schedule_reconnect(self):
        """Schedule reconnection attempt from callback thread"""
        if self._reconnect_task and not self._reconnect_task.done():
            return

        # Schedule reconnection in the event loop thread-safely
        if self._event_loop and not self._event_loop.is_closed():

            def create_reconnect_task():
                if not self._shutdown_event.is_set():
                    self._reconnect_task = asyncio.create_task(self._reconnect_loop())

            self._event_loop.call_soon_threadsafe(create_reconnect_task)
        else:
            logger.warning("Cannot schedule reconnection: no event loop available")

    async def _reconnect_loop(self):
        """Reconnection loop with exponential backoff"""
        while (
            not self._shutdown_event.is_set()
            and self.state != ConnectionState.CONNECTED
        ):
            if self.reconnect_attempts >= self.config.max_reconnect_attempts:
                logger.error("Maximum reconnection attempts reached")
                self.state = ConnectionState.FAILED
                break

            self.reconnect_attempts += 1
            self.state = ConnectionState.RECONNECTING

            # Exponential backoff with jitter
            delay = self.config.get_jittered_backoff_delay(self.reconnect_attempts - 1)
            logger.info(
                f"Reconnecting in {delay} seconds (attempt {self.reconnect_attempts})"
            )

            try:
                await asyncio.sleep(delay)

                if self._shutdown_event.is_set():
                    break

                success = await self.connect()
                if success:
                    logger.info("Reconnection successful")
                    break

            except Exception as e:
                logger.error(f"Reconnection attempt failed: {e}")

    async def _resubscribe_topics(self):
        """Resubscribe to all topics after reconnection"""
        topics_to_resubscribe = self.subscriptions.copy()
        topics_to_resubscribe.update(self.pending_subscriptions)

        for topic in topics_to_resubscribe:
            await self.subscribe(topic)

        self.pending_subscriptions.clear()

    def _get_connection_error_message(self, rc: int) -> str:
        """Get human-readable connection error message"""
        error_messages = {
            1: "Connection refused - incorrect protocol version",
            2: "Connection refused - invalid client identifier",
            3: "Connection refused - server unavailable",
            4: "Connection refused - bad username or password (check API key)",
            5: "Connection refused - not authorized (check permissions)",
        }

        return error_messages.get(rc, f"Unknown error code {rc}")

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

    def get_connection_info(self) -> Dict[str, Any]:
        """Get current connection information"""
        return {
            "state": self.state.value,
            "broker_host": self.config.broker_host,
            "broker_port": self.config.broker_port,
            "client_id": self.client.client_id if self.client else None,
            "subscriptions": list(self.subscriptions),
            "messages_received": self.messages_received,
            "messages_sent": self.messages_sent,
            "last_message_time": (
                self.last_message_time.isoformat() if self.last_message_time else None
            ),
            "connection_start_time": (
                self.connection_start_time.isoformat()
                if self.connection_start_time
                else None
            ),
            "reconnect_attempts": self.reconnect_attempts,
        }

    def get_health_status(self) -> Dict[str, Any]:
        """Get health status for monitoring"""
        now = datetime.now()

        # Calculate uptime
        uptime_seconds = 0
        if self.connection_start_time:
            uptime_seconds = (now - self.connection_start_time).total_seconds()

        # Calculate message rate
        message_rate = 0
        if self.last_message_time and self.connection_start_time:
            duration = (now - self.connection_start_time).total_seconds()
            if duration > 0:
                message_rate = self.messages_received / duration

        return {
            "status": (
                "healthy" if self.state == ConnectionState.CONNECTED else "unhealthy"
            ),
            "state": self.state.value,
            "uptime_seconds": uptime_seconds,
            "messages_received": self.messages_received,
            "messages_sent": self.messages_sent,
            "message_rate": round(message_rate, 2),
            "active_subscriptions": len(self.subscriptions),
            "reconnect_attempts": self.reconnect_attempts,
            "last_message_age_seconds": (
                (now - self.last_message_time).total_seconds()
                if self.last_message_time
                else None
            ),
        }
