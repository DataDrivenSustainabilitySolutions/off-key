"""
MQTT Connection Manager

Handles all connection lifecycle management including connect/disconnect,
TLS configuration, authentication, and automatic reconnection with backoff.
"""

import asyncio
import ssl
from datetime import datetime
from typing import Optional, Callable, Awaitable

import paho.mqtt.client as mqtt
from off_key_core.config.logs import logger
from ..config import MQTTConfig
from ..auth import ApiKeyAuthHandler, ApiKeyAuthError
from .models import ConnectionState


class ConnectionManager:
    """
    Manages MQTT connection lifecycle and state

    Handles connection establishment, TLS setup, authentication,
    disconnection, and automatic reconnection with exponential backoff.
    """

    def __init__(
        self,
        config: MQTTConfig,
        auth_handler: Optional[ApiKeyAuthHandler] = None,
        on_connected: Optional[Callable[[], Awaitable[None]]] = None,
        on_disconnected: Optional[Callable[[bool], Awaitable[None]]] = None,
    ):
        self.config = config
        self.auth_handler = auth_handler
        self.on_connected = on_connected
        self.on_disconnected = on_disconnected

        # Connection state
        self.state = ConnectionState.DISCONNECTED
        self.client: Optional[mqtt.Client] = None
        self.last_connection_attempt = 0
        self.reconnect_attempts = 0
        self.connection_start_time: Optional[datetime] = None

        # Async coordination
        self._connection_event = asyncio.Event()
        self._shutdown_event = asyncio.Event()
        self._reconnect_task: Optional[asyncio.Task] = None
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def is_connected(self) -> bool:
        """Check if currently connected"""
        return self.state == ConnectionState.CONNECTED

    @property
    def is_shutdown(self) -> bool:
        """Check if shutdown has been requested"""
        return self._shutdown_event.is_set()

    async def connect(self) -> bool:
        """
        Connect to MQTT broker with authentication

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
            # Create MQTT client
            client_id = self.config.get_client_id()

            # Use TCP transport for anonymous connections, WebSocket for authenticated ones
            transport = "tcp" if not self.auth_handler else "websockets"
            self.client = mqtt.Client(client_id=client_id, transport=transport)

            # Configure TLS
            if self.config.use_tls:
                context = ssl.create_default_context()
                if transport == "websockets":
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE  # For WebSocket connections
                self.client.tls_set_context(context)

            # Set authentication if auth handler is provided
            if self.auth_handler:
                username, password = await self.auth_handler.get_mqtt_credentials()
                self.client.username_pw_set(username, password)

            # Set callbacks
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_log = self._on_log

            # Connect to broker with reduced keep-alive for WebSocket stability
            self.client.connect_async(
                self.config.broker_host,
                self.config.broker_port,
                keepalive=15,  # Reduced from 60 to prevent network timeouts
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

                    # Notify connected callback
                    if self.on_connected:
                        await self.on_connected()

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

    async def disconnect(self) -> None:
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

    def get_connection_info(self) -> dict:
        """Get connection information for monitoring"""
        return {
            "state": self.state.value,
            "broker_host": self.config.broker_host,
            "broker_port": self.config.broker_port,
            "client_id": self.client.client_id if self.client else None,
            "connection_start_time": (
                self.connection_start_time.isoformat()
                if self.connection_start_time
                else None
            ),
            "reconnect_attempts": self.reconnect_attempts,
        }

    def get_uptime_seconds(self) -> float:
        """Get connection uptime in seconds"""
        if not self.connection_start_time:
            return 0
        return (datetime.now() - self.connection_start_time).total_seconds()

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
                # Notify disconnected callback
                if self.on_disconnected and self._event_loop:
                    self._event_loop.call_soon_threadsafe(
                        lambda: asyncio.create_task(self.on_disconnected(True))
                    )
        else:
            logger.info("MQTT disconnection completed")
            # Notify disconnected callback
            if self.on_disconnected and self._event_loop:
                self._event_loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(self.on_disconnected(False))
                )

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
                f"Reconnecting in {delay:.1f} seconds "
                f"(attempt {self.reconnect_attempts})"
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
