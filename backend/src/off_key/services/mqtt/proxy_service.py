"""
Main MQTT Proxy Service Orchestrator

Orchestrates all MQTT proxy service components including API-Key authentication,
MQTT client, charger discovery, database writer, and message router.
"""

import asyncio
import signal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ...core.config import settings
from ...core.logs import logger
from ...db.base import AsyncSessionLocal
from .api_key_auth import ApiKeyAuthHandler
from .mqtt_client import MQTTClient
from .charger_discovery import ChargerDiscoveryService
from ...core.client.base_client import ChargerAPIClient
from .database_writer import DatabaseWriter
from .message_router import MessageRouter, DatabaseDestination


class MQTTProxyService:
    """
    Main MQTT Proxy Service that orchestrates all components

    This service:
    1. Initializes all components
    2. Manages component lifecycle
    3. Handles graceful shutdown
    4. Coordinates message flow
    """

    def __init__(self, api_client: ChargerAPIClient):
        self.api_client = api_client
        self.config = settings.mqtt_config
        self.db_session: Optional[AsyncSession] = None

        # Core components
        self.auth_handler: Optional[ApiKeyAuthHandler] = None
        self.mqtt_client: Optional[MQTTClient] = None
        self.charger_discovery: Optional[ChargerDiscoveryService] = None
        self.database_writer: Optional[DatabaseWriter] = None
        self.message_router: Optional[MessageRouter] = None

        # Service state
        self.is_running = False
        self.shutdown_event = asyncio.Event()

        # Logging context
        self._log_context = {"component": "proxy_service", "service": "mqtt_proxy"}

    async def start(self):
        """Start the MQTT proxy service"""
        if self.is_running:
            logger.warning(
                "MQTT proxy service already running", extra=self._log_context
            )
            return

        logger.info("Starting MQTT proxy service", extra=self._log_context)

        try:
            # Initialize database session
            self.db_session = AsyncSessionLocal()

            # Initialize API-Key authentication
            self.auth_handler = ApiKeyAuthHandler(
                self.config.mqtt_username, self.config.mqtt_api_key
            )

            # Authenticate with API-Key (simple validation)
            await self.auth_handler.authenticate()

            # Initialize MQTT client
            self.mqtt_client = MQTTClient(self.config, self.auth_handler)
            self.mqtt_client.set_message_handler(self._handle_mqtt_message)

            # Connect to MQTT broker
            connected = await self.mqtt_client.connect()
            if not connected:
                raise RuntimeError("Failed to connect to MQTT broker")

            # Initialize charger discovery
            self.charger_discovery = ChargerDiscoveryService(
                self.config,
                self.db_session,
                self.api_client,
            )

            # Discover chargers and subscribe to topics
            chargers = await self.charger_discovery.discover_chargers()
            logger.info(
                f"Discovered {len(chargers)} chargers",
                extra={**self._log_context, "charger_count": len(chargers)},
            )

            # Subscribe to all charger topics
            for charger_info in chargers:
                await self.charger_discovery.subscribe_to_charger_topics(
                    self.mqtt_client, charger_info
                )

            # Initialize database writer
            self.database_writer = DatabaseWriter(self.config, self.db_session)
            await self.database_writer.start()

            # Initialize message router
            self.message_router = MessageRouter(self.config)
            await self.message_router.start()

            # Add database destination as default
            db_destination = DatabaseDestination(self.database_writer)
            self.message_router.add_destination(db_destination, is_default=True)

            self.is_running = True

            logger.info(
                "MQTT proxy service started successfully",
                extra={
                    **self._log_context,
                    "chargers_discovered": len(chargers),
                    "subscribed_topics": len(self.charger_discovery.get_all_topics()),
                },
            )

        except Exception as e:
            logger.error(
                f"Failed to start MQTT proxy service: {e}",
                extra=self._log_context,
                exc_info=True,
            )

            # Cleanup on failure
            await self.stop()
            raise

    async def stop(self):
        """Stop the MQTT proxy service"""
        if not self.is_running:
            logger.info("MQTT proxy service already stopped", extra=self._log_context)
            return

        logger.info("Stopping MQTT proxy service", extra=self._log_context)

        # Signal shutdown
        self.shutdown_event.set()
        self.is_running = False

        # Stop components in reverse order
        components = [
            ("message_router", self.message_router),
            ("database_writer", self.database_writer),
            ("mqtt_client", self.mqtt_client),
            ("auth_handler", self.auth_handler),
        ]

        for component_name, component in components:
            if component:
                try:
                    if hasattr(component, "stop"):
                        await component.stop()
                    elif hasattr(component, "close"):
                        await component.close()
                    elif hasattr(component, "disconnect"):
                        await component.disconnect()

                    logger.debug(
                        f"Stopped component: {component_name}",
                        extra={**self._log_context, "component": component_name},
                    )

                except Exception as e:
                    logger.error(
                        f"Error stopping component {component_name}: {e}",
                        extra={**self._log_context, "component": component_name},
                        exc_info=True,
                    )

        # Close database session
        if self.db_session:
            await self.db_session.close()

        logger.info("MQTT proxy service stopped", extra=self._log_context)

    async def _handle_mqtt_message(self, message):
        """Handle incoming MQTT messages"""
        try:
            # Route message through message router
            if self.message_router:
                await self.message_router.route_message(message)

        except Exception as e:
            logger.error(
                f"Error handling MQTT message: {e}",
                extra={**self._log_context, "topic": message.topic, "error": str(e)},
                exc_info=True,
            )

    async def run(self):
        """Run the MQTT proxy service"""

        # Set up signal handlers for graceful shutdown
        def signal_handler(signum, frame):
            logger.info(
                f"Received signal {signum}, initiating graceful shutdown",
                extra=self._log_context,
            )
            asyncio.create_task(self.stop())

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            # Start the service
            await self.start()

            # Keep running until shutdown signal
            await self.shutdown_event.wait()

        except Exception as e:
            logger.error(
                f"Unexpected error in MQTT proxy service: {e}",
                extra=self._log_context,
                exc_info=True,
            )

        finally:
            # Ensure cleanup
            await self.stop()

    def get_health_status(self):
        """Get current health status"""
        status = {
            "status": "healthy" if self.is_running else "stopped",
            "components": {},
        }

        if self.mqtt_client:
            status["components"]["mqtt_client"] = {
                "connected": self.mqtt_client.state.value == "connected"
            }

        if self.database_writer:
            status["components"][
                "database_writer"
            ] = self.database_writer.get_health_status()

        if self.message_router:
            status["components"][
                "message_router"
            ] = self.message_router.get_health_status()

        if self.charger_discovery:
            status["components"][
                "charger_discovery"
            ] = self.charger_discovery.get_health_status()

        return status

    def get_performance_metrics(self):
        """Get performance metrics"""
        metrics = {}

        if self.mqtt_client:
            metrics["mqtt_client"] = self.mqtt_client.get_connection_info()

        if self.database_writer:
            metrics["database_writer"] = self.database_writer.get_performance_metrics()

        if self.message_router:
            metrics["message_router"] = self.message_router.get_performance_metrics()

        if self.charger_discovery:
            metrics["charger_discovery"] = (
                self.charger_discovery.get_discovery_metrics()
            )

        return metrics
