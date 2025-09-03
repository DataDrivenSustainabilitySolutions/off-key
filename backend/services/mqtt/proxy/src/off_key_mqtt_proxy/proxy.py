"""
Main MQTT Proxy Service Orchestrator

Orchestrates all MQTT proxy service components including API-Key authentication,
MQTT client, charger discovery, database writer, and message router.
"""

import asyncio
import signal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from off_key_core.config.logs import logger
from off_key_core.db.base import AsyncSessionLocal
from off_key_core.utils.enum import HealthStatus
from .config import mqtt_settings
from .auth import ApiKeyAuthHandler
from .client.facade import MQTTClient
from .charger_discovery import ChargerDiscoveryService
from off_key_core.clients.base_client import ChargerAPIClient
from .telemetry import DatabaseWriter
from .router import MessageRouter, DatabaseDestination
from .core.interfaces import Stoppable, ShutdownFailedError

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
        self.config = mqtt_settings.config
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

    async def _safe_component_shutdown(
        self, name: str, component: Stoppable, timeout: float = None
    ) -> Optional[Exception]:
        """
        Safely shutdown a component with timeout protection.

        Args:
            name: Component name for logging
            component: Component to shut down
            timeout: Shutdown timeout in seconds (uses config default if None)

        Returns:
            Exception if shutdown failed, None if successful
        """
        if timeout is None:
            timeout = self.config.shutdown_timeout

        try:
            await asyncio.wait_for(component.stop(), timeout=timeout)
            logger.debug(
                f"Component {name} stopped successfully",
                extra={**self._log_context, "component": name, "timeout": timeout},
            )
            return None

        except asyncio.TimeoutError:
            error = TimeoutError(
                f"Component {name} shutdown timed out after {timeout}s"
            )
            logger.error(
                f"Component {name} shutdown timed out",
                extra={
                    **self._log_context,
                    "component": name,
                    "timeout": timeout,
                    "error": "timeout",
                },
            )
            return error

        except Exception as e:
            logger.error(
                f"Component {name} shutdown failed: {e}",
                extra={**self._log_context, "component": name, "error": str(e)},
                exc_info=True,
            )
            return e

    async def _graceful_shutdown_with_timeout(self) -> list[Exception]:
        """
        Perform graceful shutdown with total timeout protection.

        Multi-stage shutdown strategy:
        1. Graceful component shutdown (with individual timeouts)
        2. Critical resource cleanup (database session)
        3. Log results and return errors

        Returns:
            List of exceptions that occurred during shutdown
        """
        shutdown_errors = []

        # Components to stop in reverse order (dependency order)
        components = [
            ("message_router", self.message_router),
            ("database_writer", self.database_writer),
            ("mqtt_client", self.mqtt_client),
            ("auth_handler", self.auth_handler),
        ]

        try:
            # Stage 1: Graceful component shutdown
            logger.debug(
                "Starting graceful component shutdown",
                extra={**self._log_context, "stage": "component_shutdown"},
            )

            for component_name, component in components:
                if component:
                    error = await self._safe_component_shutdown(
                        component_name, component
                    )
                    if error:
                        shutdown_errors.append(error)

        except Exception as e:
            # Shouldn't happen since _safe_component_shutdown catches all exceptions
            logger.critical(
                f"Unexpected error during component shutdown: {e}",
                extra=self._log_context,
                exc_info=True,
            )
            shutdown_errors.append(e)

        finally:
            # Stage 2: Critical resource cleanup (GUARANTEED)
            logger.debug(
                "Starting critical resource cleanup",
                extra={**self._log_context, "stage": "critical_cleanup"},
            )

            if self.db_session:
                try:
                    await self.db_session.close()
                    logger.info("Database session closed", extra=self._log_context)
                except Exception as e:
                    logger.error(
                        f"Failed to close database session: {e}",
                        extra=self._log_context,
                        exc_info=True,
                    )
                    shutdown_errors.append(e)

        return shutdown_errors

    async def stop(self):
        """Stop the MQTT proxy service with robust multi-stage shutdown"""
        if not self.is_running:
            logger.info("MQTT proxy service already stopped", extra=self._log_context)
            return

        logger.info("Stopping MQTT proxy service", extra=self._log_context)
        shutdown_start_time = asyncio.get_event_loop().time()

        # Signal shutdown immediately
        self.shutdown_event.set()
        self.is_running = False

        try:
            # Perform graceful shutdown with total timeout protection
            shutdown_errors = await asyncio.wait_for(
                self._graceful_shutdown_with_timeout(),
                timeout=self.config.graceful_shutdown_timeout,
            )

            # Stage 3: Log results and handle errors
            shutdown_duration = asyncio.get_event_loop().time() - shutdown_start_time

            if shutdown_errors:
                logger.warning(
                    f"MQTT proxy service stopped with {len(shutdown_errors)} errors "
                    f"in {shutdown_duration:.2f}s",
                    extra={
                        **self._log_context,
                        "error_count": len(shutdown_errors),
                        "shutdown_duration": shutdown_duration,
                    },
                )
                # Raise aggregated exception with all shutdown errors
                raise ShutdownFailedError(
                    "MQTT proxy service shutdown failed for some components",
                    errors=shutdown_errors,
                )
            else:
                logger.info(
                    f"MQTT proxy service stopped successfully "
                    f"in {shutdown_duration:.2f}s",
                    extra={**self._log_context, "shutdown_duration": shutdown_duration},
                )

        except asyncio.TimeoutError:
            # Graceful shutdown timed out - log critical failure and exit
            shutdown_duration = asyncio.get_event_loop().time() - shutdown_start_time
            logger.critical(
                f"MQTT proxy service graceful shutdown timed out after "
                f"{self.config.graceful_shutdown_timeout}s "
                f"(total: {shutdown_duration:.2f}s). "
                "Exiting without further cleanup. "
                "Orchestrator should handle process termination.",
                extra={
                    **self._log_context,
                    "shutdown_timeout": self.config.graceful_shutdown_timeout,
                    "actual_duration": shutdown_duration,
                    "stage": "timeout_critical_failure",
                },
            )
            # Don't attempt further cleanup - let the orchestrator handle it
            raise TimeoutError(
                f"MQTT proxy service shutdown timed out after "
                f"{self.config.graceful_shutdown_timeout}s"
            )

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
           "status": (
                HealthStatus.HEALTHY if self.is_running else HealthStatus.DISABLED
            ),
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
