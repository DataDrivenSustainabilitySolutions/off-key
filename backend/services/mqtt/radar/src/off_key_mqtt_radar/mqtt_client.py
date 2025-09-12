"""
MQTT Client for RADAR service

Subscribes to internal MQTT bridge topics and feeds data to anomaly detection pipeline.
Implements resilient connection handling and message processing.
"""

import asyncio
import ssl
import time
import uuid
from datetime import datetime
from typing import Callable, Optional, Awaitable, Dict, Any
from collections import deque

import paho.mqtt.client as mqtt
from off_key_core.config.logs import logger

from .config import MQTTRadarConfig
from .models import MQTTMessage


class RadarMQTTClient:
    """
    MQTT client for RADAR service

    Handles connection to MQTT broker and message processing with:
    - Automatic reconnection
    - Topic subscription management
    - Message validation and parsing
    - Rate limiting and error handling
    """

    def __init__(self, config: MQTTRadarConfig):
        self.config = config
        self.client: Optional[mqtt.Client] = None
        self.message_handler: Optional[Callable[[MQTTMessage], Awaitable[None]]] = None

        # Connection state
        self.is_connected = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 5.0  # seconds

        # Message processing
        self.message_queue = asyncio.Queue(maxsize=config.max_queue_size)
        self.message_count = 0
        self.error_count = 0

        # Rate limiting
        self.rate_limiter = deque(maxlen=config.rate_limit_per_minute)

        # Performance tracking
        self.connection_time = None
        self.last_message_time = None

        # Event loop for async coordination
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._message_processor_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        logger.info(
            f"Initialized RADAR MQTT client "
            f"for broker {config.broker_host}:{config.broker_port}"
        )

    async def start(self):
        """Start the MQTT client and message processing"""
        self._loop = asyncio.get_running_loop()

        # Start message processor
        self._message_processor_task = asyncio.create_task(self._message_processor())

        # Connect to MQTT broker
        await self._connect()

        logger.info("RADAR MQTT client started successfully")

    async def stop(self):
        """Stop the MQTT client and cleanup resources"""
        logger.info("Stopping RADAR MQTT client")

        # Signal shutdown
        self._shutdown_event.set()

        # Disconnect from broker
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
            self.client = None

        # Cancel message processor
        if self._message_processor_task:
            self._message_processor_task.cancel()
            try:
                await self._message_processor_task
            except asyncio.CancelledError:
                pass

        self.is_connected = False
        logger.info("RADAR MQTT client stopped")

    def set_message_handler(self, handler: Callable[[MQTTMessage], Awaitable[None]]):
        """Set the message handler for processing incoming messages"""
        self.message_handler = handler

    async def _connect(self):
        """Connect to MQTT broker with authentication and TLS support"""
        try:
            # Create client with unique ID
            client_id = f"{self.config.client_id_prefix}-{uuid.uuid4().hex[:8]}"

            # Use TCP transport for simplicity (bridge handles WebSocket if needed)
            self.client = mqtt.Client(client_id=client_id, transport="tcp")

            # Configure TLS if required
            if self.config.use_tls:
                context = ssl.create_default_context()
                self.client.tls_set_context(context)

            # Set authentication if required
            if self.config.use_auth and self.config.username:
                self.client.username_pw_set(self.config.username, self.config.api_key)

            # Set callbacks
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message
            self.client.on_log = self._on_log

            # Connect to broker
            logger.info(
                f"Connecting to MQTT broker at "
                f"{self.config.broker_host}:{self.config.broker_port}"
            )
            self.client.connect_async(
                self.config.broker_host, self.config.broker_port, keepalive=60
            )

            # Start network loop
            self.client.loop_start()

            # Wait for connection (with timeout)
            connection_timeout = 30.0
            start_time = time.time()

            while (
                not self.is_connected
                and (time.time() - start_time) < connection_timeout
            ):
                await asyncio.sleep(0.1)

            if not self.is_connected:
                raise RuntimeError("Failed to connect to MQTT broker within timeout")

            logger.info("Successfully connected to MQTT broker")
            self.connection_time = datetime.now()
            self.reconnect_attempts = 0

        except Exception as e:
            logger.error(f"MQTT connection failed: {e}")
            await self._schedule_reconnect()

    def _on_connect(self, client, userdata, flags, rc):
        """MQTT connection callback"""
        if rc == 0:
            self.is_connected = True
            logger.info("MQTT connection established")

            # Subscribe to configured topics
            for topic in self.config.subscription_topics:
                try:
                    result = client.subscribe(topic, self.config.subscription_qos)
                    logger.info(f"Subscribed to topic: {topic} (result: {result})")
                except Exception as e:
                    logger.error(f"Failed to subscribe to topic {topic}: {e}")

        else:
            error_messages = {
                1: "Connection refused - incorrect protocol version",
                2: "Connection refused - invalid client identifier",
                3: "Connection refused - server unavailable",
                4: "Connection refused - bad username or password",
                5: "Connection refused - not authorized",
            }

            error_msg = error_messages.get(rc, f"Unknown error code {rc}")
            logger.error(f"MQTT connection failed: {error_msg}")
            self.is_connected = False

    def _on_disconnect(self, client, userdata, rc):
        """MQTT disconnection callback"""
        self.is_connected = False

        if rc != 0:
            logger.warning(f"Unexpected MQTT disconnection (code: {rc})")
            # Schedule reconnection
            if self._loop and not self._shutdown_event.is_set():
                self._loop.create_task(self._schedule_reconnect())
        else:
            logger.info("MQTT disconnection completed")

    def _on_message(self, client, userdata, msg):
        """MQTT message callback"""
        try:
            # Check rate limiting
            current_time = time.time()
            self.rate_limiter.append(current_time)

            # Remove old entries (older than 1 minute)
            minute_ago = current_time - 60
            while self.rate_limiter and self.rate_limiter[0] < minute_ago:
                self.rate_limiter.popleft()

            # Check rate limit
            if len(self.rate_limiter) > self.config.rate_limit_per_minute:
                logger.warning("Rate limit exceeded, dropping message")
                return

            # Create message object
            message = MQTTMessage(
                topic=msg.topic,
                payload=msg.payload,
                qos=msg.qos,
                retain=msg.retain,
                timestamp=datetime.now(),
            )

            # Add to processing queue
            try:
                self.message_queue.put_nowait(message)
                self.message_count += 1
                self.last_message_time = datetime.now()
            except asyncio.QueueFull:
                logger.warning("Message queue full, dropping message")
                self.error_count += 1

        except Exception as e:
            logger.error(f"Error processing MQTT message: {e}")
            self.error_count += 1

    def _on_log(self, client, userdata, level, buf):
        """MQTT log callback"""
        if level == mqtt.MQTT_LOG_ERR:
            logger.error(f"MQTT: {buf}")
        elif level == mqtt.MQTT_LOG_WARNING:
            logger.warning(f"MQTT: {buf}")
        else:
            logger.debug(f"MQTT: {buf}")

    async def _message_processor(self):
        """Process messages from the queue asynchronously"""
        logger.info("Started MQTT message processor")

        try:
            while not self._shutdown_event.is_set():
                try:
                    # Get message with timeout
                    message = await asyncio.wait_for(
                        self.message_queue.get(), timeout=1.0
                    )

                    # Process message if handler is set
                    if self.message_handler:
                        try:
                            await self.message_handler(message)
                        except Exception as e:
                            logger.error(f"Message handler error: {e}")
                            self.error_count += 1
                    else:
                        logger.debug(
                            f"No message handler set,"
                            f" dropping message from {message.topic}"
                        )

                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Message processor error: {e}")
                    self.error_count += 1
                    await asyncio.sleep(1.0)

        except asyncio.CancelledError:
            logger.info("Message processor cancelled")
        except Exception as e:
            logger.error(f"Message processor failed: {e}")

        logger.info("Message processor stopped")

    async def _schedule_reconnect(self):
        """Schedule reconnection attempt with exponential backoff"""
        if self._shutdown_event.is_set():
            return

        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error("Maximum reconnection attempts reached")
            return

        self.reconnect_attempts += 1
        delay = min(
            self.reconnect_delay * (2 ** (self.reconnect_attempts - 1)), 300
        )  # Max 5 minutes

        logger.info(
            f"Scheduling reconnection attempt {self.reconnect_attempts}"
            f" in {delay:.1f} seconds"
        )
        await asyncio.sleep(delay)

        if not self._shutdown_event.is_set():
            await self._connect()

    def get_connection_info(self) -> Dict[str, Any]:
        """Get connection information for monitoring"""
        uptime = None
        if self.connection_time:
            uptime = (datetime.now() - self.connection_time).total_seconds()

        last_message_age = None
        if self.last_message_time:
            last_message_age = (datetime.now() - self.last_message_time).total_seconds()

        return {
            "connected": self.is_connected,
            "broker_host": self.config.broker_host,
            "broker_port": self.config.broker_port,
            "client_id": self.client._client_id if self.client else None,
            "subscribed_topics": self.config.subscription_topics,
            "connection_time": (
                self.connection_time.isoformat() if self.connection_time else None
            ),
            "uptime_seconds": uptime,
            "reconnect_attempts": self.reconnect_attempts,
            "message_count": self.message_count,
            "error_count": self.error_count,
            "queue_size": self.message_queue.qsize(),
            "last_message_age_seconds": last_message_age,
            "rate_limit_status": {
                "current_rate": len(self.rate_limiter),
                "limit": self.config.rate_limit_per_minute,
            },
        }

    def get_health_status(self) -> Dict[str, Any]:
        """Get health status information"""
        if not self.is_connected:
            return {
                "status": "unhealthy",
                "reason": "not_connected",
                "reconnect_attempts": self.reconnect_attempts,
            }

        # Check message processing health
        queue_usage = self.message_queue.qsize() / self.config.max_queue_size
        error_rate = self.error_count / max(self.message_count, 1)

        if queue_usage > 0.9:
            status = "degraded"
            reason = "queue_nearly_full"
        elif error_rate > 0.1:
            status = "degraded"
            reason = "high_error_rate"
        else:
            status = "healthy"
            reason = "ok"

        return {
            "status": status,
            "reason": reason,
            "queue_usage": queue_usage,
            "error_rate": error_rate,
            "connected": self.is_connected,
            "uptime_seconds": (
                (datetime.now() - self.connection_time).total_seconds()
                if self.connection_time
                else 0
            ),
        }
