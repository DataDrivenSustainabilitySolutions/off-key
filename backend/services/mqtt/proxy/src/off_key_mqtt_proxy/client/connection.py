"""
MQTT Connection Manager

Connects, authenticates and disconnects one paho client. Reconnection is the
collection loop's job (MQTTProxyService._refresh_configuration): it pauses the
buffer, reconnects and re-applies subscriptions, so this class never retries.
"""

import asyncio
import ssl
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any

import paho.mqtt.client as mqtt
from off_key_core.config.logs import logger
from off_key_core.utils.mqtt_lifecycle import close_client, connack_refusal

from ..config.config import MQTTConfig
from .models import ConnectionState


class ConnectionManager:
    """
    Manages MQTT connection lifecycle and state

    Handles connection establishment, TLS setup, authentication and
    disconnection.
    """

    def __init__(
        self,
        config: MQTTConfig,
        on_connected: Callable[[], Coroutine[Any, Any, None]] | None = None,
    ):
        self.config = config
        self.on_connected = on_connected

        # Connection state
        self.state = ConnectionState.DISCONNECTED
        self.client: mqtt.Client | None = None
        self.connection_start_time: datetime | None = None

        # Async coordination
        self._connection_event = asyncio.Event()
        self._event_loop: asyncio.AbstractEventLoop | None = None

    @property
    def is_connected(self) -> bool:
        """Check if currently connected"""
        return self.state == ConnectionState.CONNECTED

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

        self._connection_event.clear()
        self.state = ConnectionState.CONNECTING
        logger.info(
            f"Connecting to MQTT broker at "
            f"{self.config.broker_host}:{self.config.broker_port}"
        )

        try:
            # Create MQTT client
            client_id = self.config.get_client_id()

            transport = self.config.transport
            await self._cleanup_failed_client()
            self.client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=client_id,
                transport=transport,
                reconnect_on_failure=False,
            )
            self.client.max_queued_messages_set(self.config.max_message_queue_size)
            self.client.max_inflight_messages_set(20)

            # Configure TLS
            if self.config.use_tls:
                context = ssl.create_default_context(cafile=self.config.ca_file)
                self.client.tls_set_context(context)

            if self.config.use_auth:
                self.client.username_pw_set(
                    self.config.mqtt_username, self.config.mqtt_api_key
                )

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

                    # Notify connected callback
                    if self.on_connected:
                        await self.on_connected()

                    return True
                logger.error("MQTT connection failed")
                return False

            except TimeoutError:
                logger.error("MQTT connection timeout")
                self.state = ConnectionState.FAILED
                await self._cleanup_failed_client()
                return False

        except asyncio.CancelledError:
            self.state = ConnectionState.FAILED
            await self._cleanup_failed_client()
            raise
        except Exception as e:
            logger.error(f"Unexpected error during MQTT connection: {e}")
            self.state = ConnectionState.FAILED
            await self._cleanup_failed_client()
            return False

    async def disconnect(self) -> None:
        """Disconnect from MQTT broker"""
        if self.client is None:
            return

        logger.info("Disconnecting from MQTT broker")
        self.state = ConnectionState.DISCONNECTED
        client, self.client = self.client, None
        await close_client(client)

        # Clear event loop reference
        self._event_loop = None

        logger.info("MQTT client disconnected")

    async def _cleanup_failed_client(self) -> None:
        """Stop and discard a paho client that did not reach connected state."""
        if not self.client:
            return
        client, self.client = self.client, None
        try:
            await close_client(client)
        except Exception:
            logger.debug("Failed MQTT client cleanup raised", exc_info=True)
        finally:
            self.client = None

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        """MQTT connection callback"""
        if client is not self.client:
            return
        if reason_code == 0:
            self.state = ConnectionState.CONNECTED
            logger.info("MQTT broker connection successful")
            if self._event_loop and not self._event_loop.is_closed():
                self._event_loop.call_soon_threadsafe(self._connection_event.set)
        else:
            self.state = ConnectionState.FAILED
            logger.error(
                f"MQTT connection failed with code {reason_code}: "
                f"{connack_refusal(reason_code)}"
            )
            if self._event_loop and not self._event_loop.is_closed():
                self._event_loop.call_soon_threadsafe(self._connection_event.set)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        """MQTT disconnection callback; the collection loop reconnects."""
        if client is not self.client:
            return
        self.state = ConnectionState.DISCONNECTED
        self._connection_event.clear()
        if reason_code != 0:
            logger.warning(f"Unexpected MQTT disconnection: {reason_code}")
        else:
            logger.info("MQTT disconnection completed")

    def _on_log(self, client, userdata, level, buf):
        """MQTT log callback"""
        if level == mqtt.MQTT_LOG_ERR:
            logger.error(f"MQTT: {buf}")
        elif level == mqtt.MQTT_LOG_WARNING:
            logger.warning(f"MQTT: {buf}")
        else:
            logger.debug(f"MQTT: {buf}")
