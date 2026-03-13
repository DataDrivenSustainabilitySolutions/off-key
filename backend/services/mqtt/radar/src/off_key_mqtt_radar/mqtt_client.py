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
from off_key_core.config.logging import get_logging_settings
from off_key_core.config.logs import logger

from .config.config import MQTTRadarConfig
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
        self.rate_limiter = deque()  # No maxlen - size controlled by time-based cleanup

        # Performance tracking
        self.connection_time = None
        self.last_message_time = None

        # Event loop for async coordination
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._message_processor_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        logging_settings = get_logging_settings()
        self._heartbeat_interval_seconds = (
            logging_settings.LOG_HEARTBEAT_INTERVAL_SECONDS
        )
        self._repeat_suppression_seconds = (
            logging_settings.LOG_REPEAT_SUPPRESSION_SECONDS
        )
        self._last_drop_summary_time = time.time()
        self._last_heartbeat_time = time.time()
        self._drop_counts: Dict[str, int] = {"rate_limit": 0, "queue_full": 0}

        logger.info(
            "event=radar.mqtt_client_initialized broker=%s:%s",
            config.broker_host,
            config.broker_port,
        )

    async def start(self):
        """Start the MQTT client and message processing"""
        self._loop = asyncio.get_running_loop()

        # Start message processor
        self._message_processor_task = asyncio.create_task(self._message_processor())

        # Connect to MQTT broker
        await self._connect()

        logger.info("event=radar.mqtt_client_started")

    async def stop(self):
        """Stop the MQTT client and cleanup resources"""
        logger.info("event=radar.mqtt_client_stopping")

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
        self._emit_drop_summary(force=True)
        logger.info("event=radar.mqtt_client_stopped")

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
                "event=radar.mqtt_connecting broker=%s:%s",
                self.config.broker_host,
                self.config.broker_port,
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

            logger.info("event=radar.mqtt_connected")
            self.connection_time = datetime.now()
            self.reconnect_attempts = 0

        except Exception as e:
            logger.error(
                "event=radar.mqtt_connect_failed error=%s", str(e), exc_info=True
            )
            await self._schedule_reconnect()

    def _on_connect(self, client, userdata, flags, rc):
        """MQTT connection callback"""
        if rc == 0:
            self.is_connected = True
            logger.info("event=radar.mqtt_connection_established")

            # Subscribe to configured topics
            for topic in self.config.subscription_topics:
                try:
                    result = client.subscribe(topic, self.config.subscription_qos)
                    logger.info(
                        "event=radar.mqtt_subscribed topic=%s result=%s",
                        topic,
                        result,
                    )
                except Exception as e:
                    logger.error(
                        "event=radar.mqtt_subscribe_failed topic=%s error=%s",
                        topic,
                        str(e),
                        exc_info=True,
                    )

        else:
            error_messages = {
                1: "Connection refused - incorrect protocol version",
                2: "Connection refused - invalid client identifier",
                3: "Connection refused - server unavailable",
                4: "Connection refused - bad username or password",
                5: "Connection refused - not authorized",
            }

            error_msg = error_messages.get(rc, f"Unknown error code {rc}")
            logger.error("event=radar.mqtt_connection_refused error=%s", error_msg)
            self.is_connected = False

    def _on_disconnect(self, client, userdata, rc):
        """MQTT disconnection callback"""
        self.is_connected = False

        if rc != 0:
            logger.warning("event=radar.mqtt_disconnected_unexpected code=%s", rc)
            # Schedule reconnection
            if self._loop and not self._shutdown_event.is_set():
                self._loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(self._schedule_reconnect())
                )
        else:
            logger.info("event=radar.mqtt_disconnected")

    def _on_message(self, client, userdata, msg):
        """MQTT message callback"""
        if not self._loop:
            logger.debug("Asyncio loop not ready, dropping incoming MQTT message")
            return

        message = MQTTMessage(
            topic=msg.topic,
            payload=msg.payload,
            qos=msg.qos,
            retain=msg.retain,
            timestamp=datetime.now(),
        )

        self._loop.call_soon_threadsafe(lambda: self._handle_incoming_message(message))

    def _handle_incoming_message(self, message: MQTTMessage):
        """Handle MQTT message on the asyncio event loop thread"""
        try:
            current_time = time.time()

            # Remove old entries (older than 1 minute)
            minute_ago = current_time - 60
            while self.rate_limiter and self.rate_limiter[0] < minute_ago:
                self.rate_limiter.popleft()

            # Check rate limit BEFORE appending
            if len(self.rate_limiter) >= self.config.rate_limit_per_minute:
                self._drop_counts["rate_limit"] += 1
                self._emit_drop_summary()
                return

            # Only append timestamp for accepted messages
            self.rate_limiter.append(current_time)

            try:
                self.message_queue.put_nowait(message)
                self.message_count += 1
                self.last_message_time = datetime.now()
            except asyncio.QueueFull:
                self._drop_counts["queue_full"] += 1
                self._emit_drop_summary()
                self.error_count += 1

        except Exception as e:
            logger.error(
                "event=radar.mqtt_message_enqueue_failed error=%s",
                str(e),
                exc_info=True,
            )
            self.error_count += 1

    def _on_log(self, client, userdata, level, buf):
        """MQTT log callback"""
        if level == mqtt.MQTT_LOG_ERR:
            logger.error("event=radar.mqtt_library_error message=%s", buf)
        elif level == mqtt.MQTT_LOG_WARNING:
            logger.warning("event=radar.mqtt_library_warning message=%s", buf)
        else:
            logger.debug("event=radar.mqtt_library_debug message=%s", buf)

    async def _message_processor(self):
        """Process messages from the queue asynchronously"""
        logger.info("event=radar.mqtt_message_processor_started")

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
                            logger.error(
                                "event=radar.mqtt_message_handler_failed error=%s",
                                str(e),
                                exc_info=True,
                            )
                            self.error_count += 1
                    else:
                        logger.debug(
                            "event=radar.mqtt_message_dropped_no_handler topic=%s",
                            message.topic,
                        )

                    self._emit_heartbeat()

                except asyncio.TimeoutError:
                    self._emit_heartbeat()
                    continue
                except Exception as e:
                    logger.error(
                        "event=radar.mqtt_message_processor_error error=%s",
                        str(e),
                        exc_info=True,
                    )
                    self.error_count += 1
                    await asyncio.sleep(1.0)

        except asyncio.CancelledError:
            logger.debug("event=radar.mqtt_message_processor_cancelled")
        except Exception as e:
            logger.error(
                "event=radar.mqtt_message_processor_failed error=%s",
                str(e),
                exc_info=True,
            )

        logger.info("event=radar.mqtt_message_processor_stopped")

    async def _schedule_reconnect(self):
        """Schedule reconnection attempt with exponential backoff"""
        if self._shutdown_event.is_set():
            return

        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error(
                "event=radar.mqtt_reconnect_exhausted attempts=%s",
                self.reconnect_attempts,
            )
            return

        self.reconnect_attempts += 1
        delay = min(
            self.reconnect_delay * (2 ** (self.reconnect_attempts - 1)), 300
        )  # Max 5 minutes

        logger.info(
            "event=radar.mqtt_reconnect_scheduled attempt=%s delay_s=%.1f",
            self.reconnect_attempts,
            delay,
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

    def _emit_drop_summary(self, *, force: bool = False) -> None:
        now = time.time()
        should_emit = force or (
            now - self._last_drop_summary_time >= self._repeat_suppression_seconds
        )
        if not should_emit:
            return

        rate_limited = self._drop_counts.get("rate_limit", 0)
        queue_full = self._drop_counts.get("queue_full", 0)
        total = rate_limited + queue_full
        if total > 0:
            logger.warning(
                "event=radar.mqtt_drop_summary total=%s rate_limit=%s \
                     queue_full=%s queue_size=%s limit=%s",
                total,
                rate_limited,
                queue_full,
                self.message_queue.qsize(),
                self.config.max_queue_size,
            )
            self._drop_counts = {"rate_limit": 0, "queue_full": 0}
        self._last_drop_summary_time = now

    def _emit_heartbeat(self) -> None:
        now = time.time()
        if now - self._last_heartbeat_time < self._heartbeat_interval_seconds:
            return

        queue_usage = self.message_queue.qsize() / max(self.config.max_queue_size, 1)
        error_rate = self.error_count / max(self.message_count, 1)
        logger.info(
            "event=radar.mqtt_heartbeat connected=%s queue_usage=%.3f \
                 message_count=%s error_count=%s \
                    error_rate=%.4f reconnect_attempts=%s",
            self.is_connected,
            queue_usage,
            self.message_count,
            self.error_count,
            error_rate,
            self.reconnect_attempts,
        )
        self._last_heartbeat_time = now
