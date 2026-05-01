"""
Main MQTT proxy service orchestrator.
"""

import asyncio
import signal
from typing import Optional

from off_key_core.config.logs import logger
from off_key_core.db.base import get_async_session_local
from off_key_core.utils.enum import HealthStatus

from .auth import ApiKeyAuthHandler
from .client.facade import MQTTClient
from .config.config import MQTTConfig, get_mqtt_settings
from .core.interfaces import ShutdownFailedError, Stoppable
from .router import BridgeDestination, DatabaseDestination, MessageRouter
from .telemetry import DatabaseWriter


class MQTTProxyService:
    """
    Main MQTT proxy service that orchestrates ingestion and bridge forwarding.
    """

    def __init__(self):
        self.config = get_mqtt_settings().config
        self.topic_extractor = self.config.build_topic_extractor()

        # Core components
        self.auth_handler: Optional[ApiKeyAuthHandler] = None
        self.mqtt_client: Optional[MQTTClient] = None
        self.database_writer: Optional[DatabaseWriter] = None
        self.message_router: Optional[MessageRouter] = None

        # Source subscription state
        self.source_subscription_status: dict[str, bool] = {}

        # Bridge components
        self.bridge_auth_handler: Optional[ApiKeyAuthHandler] = None
        self.bridge_client: Optional[MQTTClient] = None
        self.bridge_destination: Optional[BridgeDestination] = None
        self.bridge_supervisor_task: Optional[asyncio.Task] = None
        self.bridge_connected_event = asyncio.Event()

        # Service state
        self.is_running = False
        self.shutdown_event = asyncio.Event()

        # Logging context
        self._log_context = {"component": "proxy_service", "service": "mqtt_proxy"}

    async def _subscribe_source_topics(self) -> dict[str, bool]:
        if not self.mqtt_client:
            raise RuntimeError("MQTT client is not initialized")

        results: dict[str, bool] = {}
        for topic in self.config.source_topics:
            try:
                results[topic] = await self.mqtt_client.subscribe(
                    topic, qos=self.config.subscription_qos
                )
            except Exception as exc:
                logger.error(
                    "Failed to subscribe to source topic",
                    extra={**self._log_context, "topic": topic, "error": str(exc)},
                )
                results[topic] = False
        return results

    async def start(self):
        """Start the MQTT proxy service."""
        if self.is_running:
            logger.debug("event=proxy.already_running", extra=self._log_context)
            return

        logger.info("event=proxy.starting", extra=self._log_context)

        try:
            self.shutdown_event.clear()
            self.bridge_connected_event.clear()

            # Resolve cached async session factory once and reuse across DB-backed
            # components.
            session_factory = get_async_session_local()

            if self.config.use_auth:
                self.auth_handler = ApiKeyAuthHandler(
                    self.config.mqtt_username, self.config.mqtt_api_key
                )
                await self.auth_handler.authenticate()

            # Initialize MQTT client
            self.mqtt_client = MQTTClient(self.config, self.auth_handler)
            self.mqtt_client.set_message_handler(self._handle_mqtt_message)

            # Connect to source MQTT broker
            connected = await self.mqtt_client.connect()
            if not connected:
                raise RuntimeError("Failed to connect to MQTT source broker")

            # Subscribe directly to configured source topic filters
            self.source_subscription_status = await self._subscribe_source_topics()
            successful_subscriptions = sum(
                1 for ok in self.source_subscription_status.values() if ok
            )
            if successful_subscriptions == 0:
                raise RuntimeError(
                    "Failed to subscribe to all configured source topic filters"
                )

            # Initialize database writer
            self.database_writer = DatabaseWriter(
                self.config,
                session_factory,
                topic_extractor=self.topic_extractor,
            )
            await self.database_writer.start()

            # Initialize message router
            self.message_router = MessageRouter(
                self.config, topic_extractor=self.topic_extractor
            )
            await self.message_router.start()

            # Add database destination as default
            db_destination = DatabaseDestination(self.database_writer)
            self.message_router.add_destination(db_destination, is_default=True)

            self.is_running = True

            # Initialize bridge if enabled
            bridge_connected = True
            if self.config.enable_bridge:
                bridge_connected = await self._connect_bridge_once()
                self._start_bridge_supervisor()
                if not bridge_connected:
                    logger.warning(
                        "event=proxy.bridge_unavailable_startup",
                        extra={
                            **self._log_context,
                            "bridge_host": self.config.bridge_broker_host,
                            "bridge_port": self.config.bridge_broker_port,
                        },
                    )

            logger.info(
                "event=proxy.started",
                extra={
                    **self._log_context,
                    "configured_topic_filters": len(self.config.source_topics),
                    "subscribed_topics": successful_subscriptions,
                    "bridge_enabled": self.config.enable_bridge,
                    "bridge_connected": bridge_connected,
                },
            )

        except Exception as exc:
            logger.error(
                "event=proxy.start_failed error=%s",
                exc,
                extra=self._log_context,
                exc_info=True,
            )
            await self.stop()
            raise

    def _start_bridge_supervisor(self) -> None:
        """Start background bridge supervision if not already running."""
        if self.bridge_supervisor_task and not self.bridge_supervisor_task.done():
            return
        self.bridge_supervisor_task = asyncio.create_task(
            self._bridge_supervisor_loop()
        )

    async def _stop_bridge_supervisor(self) -> None:
        """Stop background bridge supervision task."""
        if self.bridge_supervisor_task and not self.bridge_supervisor_task.done():
            self.bridge_supervisor_task.cancel()
            try:
                await self.bridge_supervisor_task
            except asyncio.CancelledError:
                pass
        self.bridge_supervisor_task = None

    def _build_bridge_config(self) -> MQTTConfig:
        """Build MQTT config for the bridge target broker."""
        return MQTTConfig(
            broker_host=self.config.bridge_broker_host,
            broker_port=self.config.bridge_broker_port,
            use_tls=self.config.bridge_use_tls,
            transport=self.config.bridge_transport,
            client_id_prefix=self.config.bridge_client_id_prefix,
            use_auth=self.config.bridge_use_auth,
            mqtt_username=self.config.bridge_username,
            mqtt_api_key=self.config.bridge_api_key,
            source_topics=self.config.source_topics,
            topic_regex=self.config.topic_regex,
            topic_payload_charger_key=self.config.topic_payload_charger_key,
            topic_payload_type_key=self.config.topic_payload_type_key,
            enabled=True,
            reconnect_delay=self.config.reconnect_delay,
            max_reconnect_attempts=self.config.max_reconnect_attempts,
            batch_size=self.config.batch_size,
            batch_timeout=self.config.batch_timeout,
            subscription_qos=self.config.subscription_qos,
            health_check_interval=self.config.health_check_interval,
            health_log_reminder_interval=self.config.health_log_reminder_interval,
            connection_timeout=self.config.connection_timeout,
            max_message_queue_size=self.config.max_message_queue_size,
            worker_threads=self.config.worker_threads,
            shutdown_timeout=self.config.shutdown_timeout,
            graceful_shutdown_timeout=self.config.graceful_shutdown_timeout,
            enable_bridge=False,  # Prevent recursive bridging
            bridge_broker_host=self.config.bridge_broker_host,
            bridge_broker_port=self.config.bridge_broker_port,
            bridge_use_tls=self.config.bridge_use_tls,
            bridge_transport=self.config.bridge_transport,
            bridge_client_id_prefix=self.config.bridge_client_id_prefix,
            bridge_use_auth=self.config.bridge_use_auth,
            bridge_username=self.config.bridge_username,
            bridge_api_key=self.config.bridge_api_key,
            bridge_topic_mapping={},
        )

    async def _cleanup_existing_bridge_components(self) -> None:
        """
        Cleanup currently active bridge components before a reconnect attempt.

        Keep the destination registered, but disable it while disconnected.
        """
        if self.bridge_destination:
            self.bridge_destination.enabled = False

        if self.bridge_client:
            await self._safe_component_shutdown("bridge_client", self.bridge_client)
            self.bridge_client = None

        if self.bridge_auth_handler:
            await self._safe_component_shutdown(
                "bridge_auth_handler", self.bridge_auth_handler
            )
            self.bridge_auth_handler = None

        self.bridge_connected_event.clear()

    async def _connect_bridge_once(self) -> bool:
        """
        Attempt a single bridge connection cycle.

        Returns:
            True if connected and destination enabled, False otherwise.
        """
        if not self.message_router:
            logger.error(
                "event=proxy.bridge_setup_failed reason=router_not_initialized",
                extra=self._log_context,
            )
            return False

        if not self.config.bridge_broker_host:
            logger.error(
                "event=proxy.bridge_setup_failed reason=missing_bridge_host",
                extra=self._log_context,
            )
            return False

        if self.config.bridge_use_auth and not self.config.bridge_username:
            logger.error(
                "event=proxy.bridge_setup_failed reason=missing_bridge_username",
                extra=self._log_context,
            )
            return False

        logger.info("event=proxy.bridge_setting_up", extra=self._log_context)
        await self._cleanup_existing_bridge_components()

        bridge_auth_handler: Optional[ApiKeyAuthHandler] = None
        bridge_client: Optional[MQTTClient] = None

        try:
            if self.config.bridge_use_auth:
                bridge_auth_handler = ApiKeyAuthHandler(
                    self.config.bridge_username, self.config.bridge_api_key
                )
                await bridge_auth_handler.authenticate()

            bridge_client = MQTTClient(self._build_bridge_config(), bridge_auth_handler)
            connected = await bridge_client.connect()
            if not connected:
                raise RuntimeError("Failed to connect to bridge broker")

            self.bridge_auth_handler = bridge_auth_handler
            self.bridge_client = bridge_client
            self.bridge_connected_event.set()

            if self.bridge_destination is None:
                self.bridge_destination = BridgeDestination(
                    bridge_client, self.config.bridge_topic_mapping
                )
                self.message_router.add_destination(
                    self.bridge_destination, is_default=True
                )
            else:
                self.bridge_destination.target_client = bridge_client
            self.bridge_destination.enabled = True

            logger.info(
                "event=proxy.bridge_connected bridge_host=%s \
                     bridge_port=%s topic_mappings=%s",
                self.config.bridge_broker_host,
                self.config.bridge_broker_port,
                len(self.config.bridge_topic_mapping),
                extra={
                    **self._log_context,
                    "bridge_host": self.config.bridge_broker_host,
                    "bridge_port": self.config.bridge_broker_port,
                    "topic_mappings": len(self.config.bridge_topic_mapping),
                },
            )
            return True

        except Exception as exc:
            logger.error(
                "event=proxy.bridge_setup_failed error=%s",
                exc,
                extra=self._log_context,
                exc_info=True,
            )

            self.bridge_connected_event.clear()
            if self.bridge_destination:
                self.bridge_destination.enabled = False

            if bridge_client:
                await self._safe_component_shutdown("bridge_client", bridge_client)
            if bridge_auth_handler:
                await self._safe_component_shutdown(
                    "bridge_auth_handler", bridge_auth_handler
                )
            return False

    async def _wait_for_shutdown_or_timeout(self, timeout: float) -> bool:
        """
        Wait for either shutdown signal or timeout.

        Returns:
            True if shutdown was signaled, False if timeout elapsed.
        """
        try:
            await asyncio.wait_for(self.shutdown_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def _bridge_supervisor_loop(self) -> None:
        """Keep bridge connection healthy and reconnect on failures."""
        reconnect_attempt = 0
        logger.debug("event=proxy.bridge_supervisor_started", extra=self._log_context)

        try:
            while not self.shutdown_event.is_set():
                if not self.config.enable_bridge:
                    return

                if self.bridge_client and self.bridge_client.is_connected:
                    self.bridge_connected_event.set()
                    if self.bridge_destination:
                        self.bridge_destination.enabled = True
                    reconnect_attempt = 0

                    should_stop = await self._wait_for_shutdown_or_timeout(
                        self.config.health_monitor_interval
                    )
                    if should_stop:
                        return
                    continue

                if self.bridge_client:
                    bridge_state = getattr(
                        getattr(self.bridge_client, "state", None),
                        "value",
                        "unknown",
                    )
                    if bridge_state in {"connecting", "reconnecting"}:
                        should_stop = await self._wait_for_shutdown_or_timeout(
                            self.config.health_monitor_interval
                        )
                        if should_stop:
                            return
                        continue

                self.bridge_connected_event.clear()
                if self.bridge_destination:
                    self.bridge_destination.enabled = False

                reconnect_attempt += 1
                connected = await self._connect_bridge_once()
                if connected:
                    reconnect_attempt = 0
                    continue

                retry_delay = self.config.get_jittered_backoff_delay(
                    reconnect_attempt - 1
                )
                logger.warning(
                    "event=proxy.bridge_retry_scheduled retry_delay_s=%.2f attempt=%s",
                    retry_delay,
                    reconnect_attempt,
                    extra={
                        **self._log_context,
                        "retry_delay_seconds": retry_delay,
                        "reconnect_attempt": reconnect_attempt,
                        "bridge_host": self.config.bridge_broker_host,
                        "bridge_port": self.config.bridge_broker_port,
                    },
                )

                should_stop = await self._wait_for_shutdown_or_timeout(retry_delay)
                if should_stop:
                    return

        except asyncio.CancelledError:
            logger.debug(
                "event=proxy.bridge_supervisor_cancelled", extra=self._log_context
            )
            raise
        except Exception as exc:
            logger.error(
                "event=proxy.bridge_supervisor_failed error=%s",
                exc,
                extra=self._log_context,
                exc_info=True,
            )
        finally:
            self.bridge_connected_event.clear()
            if self.bridge_destination:
                self.bridge_destination.enabled = False
            logger.debug(
                "event=proxy.bridge_supervisor_stopped", extra=self._log_context
            )

    async def _safe_component_shutdown(
        self, name: str, component: Stoppable, timeout: Optional[float] = None
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
                "event=proxy.component_stopped component_name=%s timeout_s=%s",
                name,
                timeout,
                extra={**self._log_context, "component": name, "timeout": timeout},
            )
            return None

        except asyncio.TimeoutError:
            error = TimeoutError(
                f"Component {name} shutdown timed out after {timeout}s"
            )
            logger.error(
                "event=proxy.component_shutdown_timeout component_name=%s timeout_s=%s",
                name,
                timeout,
                extra={
                    **self._log_context,
                    "component": name,
                    "timeout": timeout,
                    "error": "timeout",
                },
            )
            return error

        except Exception as exc:
            logger.error(
                "event=proxy.component_shutdown_failed component_name=%s error=%s",
                name,
                exc,
                extra={**self._log_context, "component": name, "error": str(exc)},
                exc_info=True,
            )
            return exc

    async def _graceful_shutdown_with_timeout(self) -> list[Exception]:
        """
        Perform graceful shutdown with total timeout protection.

        Returns:
            List of exceptions that occurred during shutdown.
        """
        shutdown_errors = []

        await self._stop_bridge_supervisor()

        components = [
            ("message_router", self.message_router),
            ("database_writer", self.database_writer),
            ("bridge_client", self.bridge_client),
            ("mqtt_client", self.mqtt_client),
            ("bridge_auth_handler", self.bridge_auth_handler),
            ("auth_handler", self.auth_handler),
        ]

        try:
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

        except Exception as exc:
            logger.critical(
                f"Unexpected error during component shutdown: {exc}",
                extra=self._log_context,
                exc_info=True,
            )
            shutdown_errors.append(exc)
        finally:
            logger.debug(
                "Starting critical resource cleanup",
                extra={**self._log_context, "stage": "critical_cleanup"},
            )

        return shutdown_errors

    async def stop(self):
        """Stop the MQTT proxy service with robust multi-stage shutdown."""
        has_active_components = any(
            [
                self.auth_handler,
                self.mqtt_client,
                self.database_writer,
                self.message_router,
                self.bridge_auth_handler,
                self.bridge_client,
                self.bridge_supervisor_task and not self.bridge_supervisor_task.done(),
            ]
        )
        if not self.is_running and not has_active_components:
            logger.debug("event=proxy.already_stopped", extra=self._log_context)
            return

        logger.debug("event=proxy.stopping", extra=self._log_context)
        shutdown_start_time = asyncio.get_event_loop().time()

        self.shutdown_event.set()
        self.bridge_connected_event.clear()
        self.is_running = False

        try:
            shutdown_errors = await asyncio.wait_for(
                self._graceful_shutdown_with_timeout(),
                timeout=self.config.graceful_shutdown_timeout,
            )

            shutdown_duration = asyncio.get_event_loop().time() - shutdown_start_time

            if shutdown_errors:
                logger.warning(
                    "event=proxy.stopped_with_errors error_count=%s \
                         shutdown_duration_s=%.2f",
                    len(shutdown_errors),
                    shutdown_duration,
                    extra={
                        **self._log_context,
                        "error_count": len(shutdown_errors),
                        "shutdown_duration": shutdown_duration,
                    },
                )
                raise ShutdownFailedError(
                    "MQTT proxy service shutdown failed for some components",
                    errors=shutdown_errors,
                )

            logger.info(
                "event=proxy.stopped shutdown_duration_s=%.2f",
                shutdown_duration,
                extra={**self._log_context, "shutdown_duration": shutdown_duration},
            )

        except asyncio.TimeoutError:
            shutdown_duration = asyncio.get_event_loop().time() - shutdown_start_time
            logger.critical(
                "event=proxy.shutdown_timeout graceful_timeout_s=%s \
                     actual_duration_s=%.2f",
                self.config.graceful_shutdown_timeout,
                shutdown_duration,
                extra={
                    **self._log_context,
                    "shutdown_timeout": self.config.graceful_shutdown_timeout,
                    "actual_duration": shutdown_duration,
                    "stage": "timeout_critical_failure",
                },
            )
            raise TimeoutError(
                f"MQTT proxy service shutdown timed out after "
                f"{self.config.graceful_shutdown_timeout}s"
            )

    async def _handle_mqtt_message(self, message):
        """Handle incoming MQTT messages."""
        try:
            if self.message_router:
                await self.message_router.route_message(message)

        except Exception as exc:
            logger.error(
                "event=proxy.message_handle_failed topic=%s error=%s",
                message.topic,
                exc,
                extra={**self._log_context, "topic": message.topic, "error": str(exc)},
                exc_info=True,
            )

    async def run(self):
        """Run the MQTT proxy service."""

        def signal_handler(signum, frame):
            logger.debug(
                "event=proxy.signal_received signal=%s",
                signum,
                extra=self._log_context,
            )
            asyncio.create_task(self.stop())

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            await self.start()
            await self.shutdown_event.wait()

        except Exception as exc:
            logger.error(
                "event=proxy.run_failed error=%s",
                exc,
                extra=self._log_context,
                exc_info=True,
            )
        finally:
            await self.stop()

    def _is_bridge_supervisor_running(self) -> bool:
        return bool(
            self.bridge_supervisor_task and not self.bridge_supervisor_task.done()
        )

    def is_bridge_ready(self) -> bool:
        if not self.is_running:
            return False
        if not self.mqtt_client or not self.mqtt_client.is_connected:
            return False
        if not self.source_subscription_status:
            return False
        if not any(self.source_subscription_status.values()):
            return False
        if not self.config.enable_bridge:
            return True
        if not self.bridge_connected_event.is_set():
            return False
        if not self._is_bridge_supervisor_running():
            return False
        return bool(self.bridge_destination and self.bridge_destination.enabled)

    def get_readiness_status(self) -> dict:
        primary_connected = bool(self.mqtt_client and self.mqtt_client.is_connected)
        bridge_required = bool(self.config.enable_bridge)
        bridge_connected = bool(
            bridge_required and self.bridge_connected_event.is_set()
        )
        bridge_supervisor_running = self._is_bridge_supervisor_running()
        destination_enabled = bool(
            self.bridge_destination and self.bridge_destination.enabled
        )
        ready = self.is_bridge_ready()

        return {
            "status": "ready" if ready else "not_ready",
            "ready": ready,
            "service": "mqtt-proxy",
            "running": self.is_running,
            "mqtt_primary_connected": primary_connected,
            "source_subscriptions": self.source_subscription_status,
            "bridge_required": bridge_required,
            "bridge_connected": bridge_connected,
            "bridge_supervisor_running": bridge_supervisor_running,
            "bridge_destination_enabled": destination_enabled,
            "bridge_host": self.config.bridge_broker_host,
            "bridge_port": self.config.bridge_broker_port,
        }

    def get_health_status(self):
        bridge_supervisor_running = self._is_bridge_supervisor_running()
        bridge_connected = bool(
            self.config.enable_bridge and self.bridge_connected_event.is_set()
        )

        status_value = (
            HealthStatus.HEALTHY if self.is_running else HealthStatus.DISABLED
        )
        if self.is_running and not any(self.source_subscription_status.values()):
            status_value = HealthStatus.UNHEALTHY
        if self.is_running and self.config.enable_bridge and not bridge_connected:
            status_value = HealthStatus.UNHEALTHY
        if (
            self.is_running
            and self.config.enable_bridge
            and not bridge_supervisor_running
        ):
            status_value = HealthStatus.UNHEALTHY

        status = {
            "status": status_value,
            "components": {
                "source_subscriptions": self.source_subscription_status,
            },
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

        if self.bridge_client:
            status["components"]["bridge_client"] = {
                "connected": self.bridge_client.state.value == "connected"
            }
        if self.config.enable_bridge:
            status["components"]["bridge"] = {
                "required": True,
                "connected": bridge_connected,
                "supervisor_running": bridge_supervisor_running,
                "destination_enabled": bool(
                    self.bridge_destination and self.bridge_destination.enabled
                ),
                "broker_host": self.config.bridge_broker_host,
                "broker_port": self.config.bridge_broker_port,
            }

        return status

    def get_performance_metrics(self):
        metrics = {
            "source_subscriptions": self.source_subscription_status,
        }

        if self.mqtt_client:
            metrics["mqtt_client"] = self.mqtt_client.get_connection_info()

        if self.database_writer:
            metrics["database_writer"] = self.database_writer.get_performance_metrics()

        if self.message_router:
            metrics["message_router"] = self.message_router.get_performance_metrics()

        if self.bridge_client:
            metrics["bridge_client"] = self.bridge_client.get_connection_info()

        return metrics
