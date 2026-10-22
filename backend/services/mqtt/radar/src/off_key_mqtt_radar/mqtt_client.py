"""
MQTT Client for RADAR service

Subscribes to internal MQTT bridge topics and feeds data to anomaly detection pipeline.
Implements resilient connection handling and message processing.
"""

import asyncio
import ssl
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from threading import Lock
from typing import Any

import janus
import paho.mqtt.client as mqtt
from off_key_core.config.logging import get_logging_settings
from off_key_core.config.logs import logger
from off_key_core.utils.mqtt_lifecycle import close_client

from .config.config import MQTTRadarConfig
from .coverage import CoverageTracker
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

    def __init__(
        self, config: MQTTRadarConfig, coverage: CoverageTracker | None = None
    ):
        self.config = config
        self.client: mqtt.Client | None = None
        self.message_handler: Callable[[MQTTMessage], Awaitable[None]] | None = None
        self.coverage = coverage if coverage is not None else CoverageTracker()

        # Connection state
        self.is_connected = False
        self.reconnect_attempts = 0
        self.reconnect_delay = 5.0  # seconds

        # Message processing
        self._message_bridge = janus.Queue(maxsize=config.max_queue_size)
        self.message_queue = self._message_bridge.async_q
        self._ingress_lock = Lock()
        self.message_count = 0
        self.error_count = 0

        # Rate limiting
        self.rate_limiter = deque()  # No maxlen - size controlled by time-based cleanup

        # Performance tracking
        self.connection_time = None
        self.last_message_time = None

        # Event loop for async coordination
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connection_result: asyncio.Future[None] | None = None
        self._connection_timeout_seconds = 30.0
        self._pending_subscriptions: dict[int, str] = {}
        self._confirmed_subscriptions: set[str] = set()
        self._message_processor_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
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
        self._drop_counts: dict[str, int] = {"rate_limit": 0, "queue_full": 0}

        logger.info(
            "event=radar.mqtt_client_initialized broker=%s:%s",
            config.broker_host,
            config.broker_port,
        )

    async def start(self):
        """Start the MQTT client and message processing"""
        self._loop = asyncio.get_running_loop()
        self._shutdown_event.clear()
        if self._message_bridge.closed:
            self._message_bridge = janus.Queue(maxsize=self.config.max_queue_size)
            self.message_queue = self._message_bridge.async_q

        # Start message processor
        self._message_processor_task = asyncio.create_task(self._message_processor())

        try:
            # Initial startup must be connected and subscribed before the service is
            # considered ready. Background reconnects are only for later failures.
            await self._connect()
        except BaseException:
            await self.stop()
            raise

        logger.info("event=radar.mqtt_client_started")

    async def stop(self):
        """Stop the MQTT client and cleanup resources"""
        logger.info("event=radar.mqtt_client_stopping")

        # Signal shutdown
        self._shutdown_event.set()

        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._reconnect_task
        self._reconnect_task = None

        # Disconnect from broker
        await self._close_client()

        # Cancel message processor
        if self._message_processor_task:
            self._message_processor_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._message_processor_task

        self.is_connected = False
        if not self._message_bridge.closed:
            pending = self.message_queue.qsize()
            if pending:
                self.coverage.record_drop("shutdown_queue", pending)
            await self._message_bridge.aclose()
        self._emit_drop_summary(force=True)
        logger.info("event=radar.mqtt_client_stopped")

    def set_message_handler(self, handler: Callable[[MQTTMessage], Awaitable[None]]):
        """Set the message handler for processing incoming messages"""
        self.message_handler = handler

    async def _connect(self):
        """Connect to MQTT broker with authentication and TLS support"""
        # RADAR owns reconnection. Retire the previous client before replacing it;
        # otherwise its network thread can reconnect and keep delivering messages.
        await self._close_client()
        try:
            loop = asyncio.get_running_loop()
            self._loop = loop
            connection_result = loop.create_future()
            self._connection_result = connection_result

            # Create client with unique ID
            client_id = f"{self.config.client_id_prefix}-{uuid.uuid4().hex[:8]}"
            self.is_connected = False

            # Use TCP transport for simplicity (bridge handles WebSocket if needed)
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=client_id,
                transport="tcp",
                reconnect_on_failure=False,
            )

            # Configure TLS if required
            if self.config.use_tls:
                context = ssl.create_default_context(cafile=self.config.ca_file)
                self.client.tls_set_context(context)

            # Set authentication if required
            if self.config.use_auth:
                self.client.username_pw_set(self.config.username, self.config.api_key)

            # Set callbacks
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message
            self.client.on_subscribe = self._on_subscribe
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

            # Paho invokes connection callbacks on its network thread. The callback
            # resolves this future on the asyncio thread without polling shared state.
            try:
                await asyncio.wait_for(
                    connection_result, timeout=self._connection_timeout_seconds
                )
            except TimeoutError as error:
                raise RuntimeError(
                    "MQTT connection or required subscription acknowledgement timed out"
                ) from error
            finally:
                if self._connection_result is connection_result:
                    self._connection_result = None

            logger.info("event=radar.mqtt_connected")
            self.connection_time = datetime.now()
            self.reconnect_attempts = 0

        except BaseException as e:
            await self._close_client()
            logger.error(
                "event=radar.mqtt_connect_failed error=%s", str(e), exc_info=True
            )
            raise

    async def _close_client(self) -> None:
        """Fence retired callbacks before stopping the owned network thread."""
        client, self.client = self.client, None
        self.is_connected = False
        self._pending_subscriptions.clear()
        self._confirmed_subscriptions.clear()
        if client is not None:
            await close_client(client)

    def _notify_connection_result(self, error: RuntimeError | None = None) -> None:
        """Resolve the active connection attempt on the asyncio event loop."""
        if not self._loop or self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(
            self._complete_connection_attempt, self.client, error
        )

    def _complete_connection_attempt(
        self, client: mqtt.Client | None, error: RuntimeError | None
    ) -> None:
        if client is not self.client:
            return
        connection_result = self._connection_result
        if not connection_result or connection_result.done():
            return
        if error:
            connection_result.set_exception(error)
        else:
            connection_result.set_result(None)

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        """MQTT connection callback"""
        if client is not self.client or self._shutdown_event.is_set():
            return
        rc = getattr(reason_code, "value", reason_code)
        if rc == 0:
            self._pending_subscriptions.clear()
            self._confirmed_subscriptions.clear()
            logger.info("event=radar.mqtt_connection_established")

            # Subscribe to configured topics
            for topic in self.config.subscription_topics:
                try:
                    result, mid = client.subscribe(topic, self.config.subscription_qos)
                    if result != mqtt.MQTT_ERR_SUCCESS:
                        raise RuntimeError(f"SUBSCRIBE failed locally: {result}")
                    self._pending_subscriptions[mid] = topic
                    logger.info(
                        "event=radar.mqtt_subscription_requested topic=%s mid=%s",
                        topic,
                        mid,
                    )
                except Exception as e:
                    logger.error(
                        "event=radar.mqtt_subscribe_failed topic=%s error=%s",
                        topic,
                        str(e),
                        exc_info=True,
                    )
                    self._notify_connection_result(
                        RuntimeError(f"Required MQTT subscription failed: {topic}: {e}")
                    )
                    return
            if not self._pending_subscriptions:
                self._notify_connection_result(
                    RuntimeError("No required MQTT subscriptions configured")
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
            self._notify_connection_result(RuntimeError(error_msg))

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties=None):
        """Readiness requires every required topic to have a successful SUBACK."""
        if client is not self.client or self._shutdown_event.is_set():
            return
        topic = self._pending_subscriptions.pop(mid, None)
        if topic is None:
            return
        granted = [getattr(code, "value", code) for code in reason_codes]
        if len(granted) != 1 or granted[0] not in (0, 1, 2):
            self.is_connected = False
            self._notify_connection_result(
                RuntimeError(f"Required MQTT subscription rejected: {topic}: {granted}")
            )
            return
        self._confirmed_subscriptions.add(topic)
        if self._confirmed_subscriptions == set(self.config.subscription_topics):
            self.is_connected = True
            self._notify_connection_result()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        """MQTT disconnection callback"""
        if client is not self.client or self._shutdown_event.is_set():
            return
        rc = getattr(reason_code, "value", reason_code)
        if self.is_connected:
            self.coverage.record_possible_gap("mqtt_disconnect")
        self.is_connected = False
        self._notify_connection_result(
            RuntimeError("Disconnected before MQTT connection was established")
        )

        if rc != 0:
            logger.warning("event=radar.mqtt_disconnected_unexpected code=%s", rc)
            # Schedule reconnection
            if (
                self._loop
                and not self._loop.is_closed()
                and not self._shutdown_event.is_set()
            ):
                self._loop.call_soon_threadsafe(self._ensure_reconnect_task)
        else:
            logger.info("event=radar.mqtt_disconnected")

    def _on_message(self, client, userdata, msg):
        """MQTT message callback"""
        if self._shutdown_event.is_set():
            return
        if not self._loop or self._loop.is_closed():
            self.coverage.record_received()
            self.coverage.record_drop("loop_unavailable")
            logger.debug("Asyncio loop not ready, dropping incoming MQTT message")
            return
        if client is not self.client:
            return

        message = MQTTMessage(
            topic=msg.topic,
            payload=msg.payload,
            qos=msg.qos,
            retain=msg.retain,
            timestamp=datetime.now(UTC),
            received_monotonic=time.monotonic(),
        )
        # Admission happens on Paho's thread before any event-loop notification.
        # Janus bounds stored messages and wakes only waiting async consumers.
        self._handle_incoming_message(message)

    def _handle_incoming_message(self, message: MQTTMessage):
        """Bound admission before crossing from the network thread to asyncio."""
        with self._ingress_lock:
            self._accept_incoming_message(message)

    def _accept_incoming_message(self, message: MQTTMessage):
        self.coverage.record_received()
        try:
            if len(message.payload) > self.config.max_payload_bytes:
                self.coverage.record_drop("payload_too_large")
                self.error_count += 1
                return
            current_time = time.monotonic()

            # Remove old entries (older than 1 minute)
            minute_ago = current_time - 60
            while self.rate_limiter and self.rate_limiter[0] < minute_ago:
                self.rate_limiter.popleft()

            # Check rate limit BEFORE appending
            limit = self.config.rate_limit_per_minute
            if limit > 0 and len(self.rate_limiter) >= limit:
                self._drop_counts["rate_limit"] += 1
                self.coverage.record_drop("rate_limit")
                self._emit_drop_summary()
                return

            # Only append timestamp for accepted messages
            if limit > 0:
                self.rate_limiter.append(current_time)

            try:
                self._message_bridge.sync_q.put_nowait(message)
                self.message_count += 1
                self.last_message_time = datetime.now()
            except janus.SyncQueueFull:
                self._drop_counts["queue_full"] += 1
                self.coverage.record_drop("queue_full")
                self._emit_drop_summary()
                self.error_count += 1

        except Exception as e:
            logger.error(
                "event=radar.mqtt_message_enqueue_failed error=%s",
                str(e),
                exc_info=True,
            )
            self.error_count += 1
            self.coverage.record_drop("enqueue_error")

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
                            self.coverage.record_drop("handler_error")
                    else:
                        self.coverage.record_drop("no_handler")
                        logger.debug(
                            "event=radar.mqtt_message_dropped_no_handler topic=%s",
                            message.topic,
                        )

                    self._emit_heartbeat()
                    self.message_queue.task_done()

                except TimeoutError:
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

    def _ensure_reconnect_task(self) -> None:
        """Create one background reconnect loop if needed."""
        if self._shutdown_event.is_set():
            return
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self):
        """Keep one owner retrying through outages with bounded backoff."""
        delay = min(self.reconnect_delay, 300.0)
        while not self._shutdown_event.is_set() and not self.is_connected:
            self.reconnect_attempts += 1

            logger.info(
                "event=radar.mqtt_reconnect_scheduled attempt=%s delay_s=%.1f",
                self.reconnect_attempts,
                delay,
            )
            try:
                await asyncio.wait_for(self._shutdown_event.wait(), timeout=delay)
                return
            except TimeoutError:
                pass

            if self._shutdown_event.is_set():
                return

            try:
                await self._connect()
            except Exception as exc:
                logger.warning(
                    "event=radar.mqtt_reconnect_attempt_failed attempt=%s error=%s",
                    self.reconnect_attempts,
                    exc,
                )
            # Doubling the already capped delay avoids unbounded exponentiation
            # when a worker survives an extended broker outage.
            delay = min(delay * 2, 300.0)

    def get_health_status(self) -> dict[str, Any]:
        """Get health status information"""
        coverage = self.coverage.snapshot().model_dump(mode="json")
        if not self.is_connected:
            return {
                "status": "unhealthy",
                "reason": "not_connected",
                "reconnect_attempts": self.reconnect_attempts,
                "coverage": coverage,
            }

        # Check message processing health
        queue_usage = self.message_queue.qsize() / self.config.max_queue_size
        error_rate = self.error_count / max(self.message_count, 1)

        if coverage["has_gaps"]:
            status = "degraded"
            reason = "coverage_gap"
        elif queue_usage > 0.9:
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
            "coverage": coverage,
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
                "event=radar.mqtt_drop_summary total=%s rate_limit=%s "
                "queue_full=%s queue_size=%s limit=%s",
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
            "event=radar.mqtt_heartbeat connected=%s queue_usage=%.3f "
            "message_count=%s error_count=%s "
            "error_rate=%.4f reconnect_attempts=%s",
            self.is_connected,
            queue_usage,
            self.message_count,
            self.error_count,
            error_rate,
            self.reconnect_attempts,
        )
        self._last_heartbeat_time = now
