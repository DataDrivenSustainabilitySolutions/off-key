"""
Message Router for MQTT Telemetry Distribution

Routes MQTT messages to configured destinations with logging and error handling.
"""

import asyncio
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from types import TracebackType
from typing import Self

from off_key_core.config.logs import logger
from off_key_core.utils.enum import HealthStatus
from off_key_core.utils.mqtt_topics import TopicMetadataExtractor

from .client.models import MQTTMessage
from .config.config import MQTTConfig
from .destinations import MessageDestination
from .routing_models import (
    MessageRouteInfo,
    RouteResult,
    RouterHealthStatus,
    RouterPerformanceMetrics,
    RouteStatus,
)


class MessageRouter:
    """
    High-performance message router for MQTT telemetry

    Features:
    - Multi-destination routing with parallel processing
    - Intelligent error handling and retry logic
    - Performance monitoring and metrics
    - Dynamic destination management
    - Intelligent logging with context
    - Circuit breaker pattern for failing destinations
    """

    def __init__(
        self,
        config: MQTTConfig,
        topic_extractor: TopicMetadataExtractor | None = None,
    ) -> None:
        self.config = config
        self.topic_extractor = topic_extractor or config.build_topic_extractor()

        # Destinations
        self.destinations: dict[str, MessageDestination] = {}
        self.default_destinations: set[str] = set()

        # Message routing
        self.active_routes: dict[str, MessageRouteInfo] = {}

        # Performance metrics
        self.total_messages_routed = 0
        self.total_successful_routes = 0
        self.total_failed_routes = 0
        self.total_routing_time = 0.0

        # Configuration
        self.max_concurrent_routes = config.worker_threads * 10
        self.route_timeout = 10.0
        self.max_retries = 2

        # Background tasks
        self._metrics_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        self._all_routes_completed_event = asyncio.Event()

        # Logging context
        self._log_context = {"component": "message_router", "service": "mqtt_proxy"}

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.stop()

    async def start(self) -> None:
        """Start the message router"""
        logger.info("event=router.started", extra=self._log_context)

        self._metrics_task = asyncio.create_task(self._metrics_loop())

        logger.info(
            "event=router.startup_complete",
            extra={
                **self._log_context,
                "max_concurrent_routes": self.max_concurrent_routes,
                "route_timeout": self.route_timeout,
            },
        )

    async def stop(self) -> None:
        """Stop the message router"""
        logger.debug("event=router.stopping", extra=self._log_context)

        # Signal shutdown
        self._shutdown_event.set()

        # Cancel background tasks
        if self._metrics_task and not self._metrics_task.done():
            self._metrics_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._metrics_task

        # Wait for active routes to complete (race-condition-free)
        # First: Handle already-complete case atomically
        if not self.active_routes:
            logger.debug(
                "event=router.active_routes_already_completed", extra=self._log_context
            )
            self._all_routes_completed_event.set()  # Ensure consistent event state

        # Second: Only wait if event is not already set (prevents race condition)
        if not self._all_routes_completed_event.is_set():
            logger.debug(
                "event=router.await_active_routes active_routes=%s",
                len(self.active_routes),
                extra={**self._log_context, "active_routes": len(self.active_routes)},
            )

            try:
                await asyncio.wait_for(
                    self._all_routes_completed_event.wait(),
                    timeout=self.config.graceful_shutdown_timeout,
                )
                logger.debug(
                    "event=router.active_routes_completed",
                    extra=self._log_context,
                )
            except TimeoutError:
                logger.warning(
                    "event=router.shutdown_timeout remaining_routes=%s timeout_s=%s",
                    len(self.active_routes),
                    self.config.graceful_shutdown_timeout,
                    extra={
                        **self._log_context,
                        "remaining_routes": len(self.active_routes),
                        "timeout": self.config.graceful_shutdown_timeout,
                    },
                )

        logger.debug("event=router.stopped", extra=self._log_context)

    def add_destination(
        self, destination: MessageDestination, is_default: bool = False
    ) -> None:
        """Add a message destination"""
        self.destinations[destination.name] = destination

        if is_default:
            self.default_destinations.add(destination.name)

        logger.info(
            "event=router.destination_added destination=%s is_default=%s total=%s",
            destination.name,
            is_default,
            len(self.destinations),
            extra={
                **self._log_context,
                "destination": destination.name,
                "is_default": is_default,
                "total_destinations": len(self.destinations),
            },
        )

    def remove_destination(self, destination_name: str) -> None:
        """Remove a message destination"""
        if destination_name in self.destinations:
            del self.destinations[destination_name]
            self.default_destinations.discard(destination_name)

            logger.info(
                "event=router.destination_removed destination=%s total=%s",
                destination_name,
                len(self.destinations),
                extra={
                    **self._log_context,
                    "destination": destination_name,
                    "total_destinations": len(self.destinations),
                },
            )

    def enable_destination(self, destination_name: str) -> None:
        """Enable a message destination"""
        if destination_name in self.destinations:
            self.destinations[destination_name].enabled = True
            logger.info(
                "event=router.destination_enabled destination=%s",
                destination_name,
                extra={**self._log_context, "destination": destination_name},
            )

    def disable_destination(self, destination_name: str) -> None:
        """Disable a message destination"""
        if destination_name in self.destinations:
            self.destinations[destination_name].enabled = False
            logger.warning(
                "event=router.destination_disabled destination=%s",
                destination_name,
                extra={**self._log_context, "destination": destination_name},
            )

    async def route_message(
        self, message: MQTTMessage, destinations: list[str] | None = None
    ) -> MessageRouteInfo:
        """
        Route message to destinations

        Args:
            message: MQTT message to route
            destinations: List of destination names (uses defaults if None)

        Returns:
            MessageRouteInfo with routing results
        """
        # Use default destinations if not specified
        if destinations is None:
            destinations = list(self.default_destinations)

        # Filter enabled destinations
        enabled_destinations = [
            dest
            for dest in destinations
            if dest in self.destinations and self.destinations[dest].enabled
        ]

        if not enabled_destinations:
            logger.warning(
                "No enabled destinations available for routing",
                extra={
                    **self._log_context,
                    "topic": message.topic,
                    "requested_destinations": destinations,
                },
            )
            return MessageRouteInfo(
                message_id=self._new_message_id(),
                topic=message.topic,
                charger_id=self._extract_charger_id(message.topic),
                timestamp=message.timestamp,
                destinations=destinations,
            )

        # Create route info
        route_info = MessageRouteInfo(
            message_id=self._new_message_id(),
            topic=message.topic,
            charger_id=self._extract_charger_id(message.topic),
            timestamp=message.timestamp,
            destinations=enabled_destinations,
        )

        # Track active route
        self._all_routes_completed_event.clear()
        self.active_routes[route_info.message_id] = route_info

        # Route message to destinations concurrently
        tasks = [
            asyncio.create_task(
                self._route_to_destination(message, dest_name, route_info)
            )
            for dest_name in enabled_destinations
        ]

        # Wait for all routes to complete with timeout
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self.route_timeout,
            )
        except TimeoutError:
            logger.error(
                "event=router.routing_timeout timeout_s=%s "
                "message_id=%s topic=%s destinations=%s",
                self.route_timeout,
                route_info.message_id,
                message.topic,
                enabled_destinations,
                extra={
                    **self._log_context,
                    "message_id": route_info.message_id,
                    "topic": message.topic,
                    "destinations": enabled_destinations,
                },
            )

            # Mark incomplete routes as timeout
            for dest_name in enabled_destinations:
                if dest_name not in route_info.results:
                    route_info.results[dest_name] = RouteResult(
                        destination=dest_name,
                        status=RouteStatus.TIMEOUT,
                        processing_time=self.route_timeout,
                        error="Routing timeout",
                    )
        finally:
            route_info.completed_at = datetime.now(UTC)
            self.active_routes.pop(route_info.message_id, None)
            if not self.active_routes:
                self._all_routes_completed_event.set()

        # Update metrics
        self.total_messages_routed += 1
        self.total_routing_time += route_info.get_processing_time()

        if route_info.get_success_count() == len(enabled_destinations):
            self.total_successful_routes += 1
        else:
            self.total_failed_routes += 1

        self._log_route_result(route_info)

        return route_info

    def _log_route_result(self, route_info: MessageRouteInfo) -> None:
        success_count = route_info.get_success_count()
        if self.total_messages_routed % 100 and success_count == len(
            route_info.destinations
        ):
            return

        extra = {
            **self._log_context,
            "message_id": route_info.message_id,
            "topic": route_info.topic,
            "destinations": route_info.destinations,
            "success_count": success_count,
            "failed_destinations": route_info.get_failed_destinations(),
            "processing_time": route_info.get_processing_time(),
            "total_routed": self.total_messages_routed,
        }
        if success_count == len(route_info.destinations):
            logger.debug(
                "event=router.routed success=%s total=%s",
                success_count,
                len(route_info.destinations),
                extra=extra,
            )
        else:
            logger.warning(
                "event=router.routed_partial success=%s total=%s",
                success_count,
                len(route_info.destinations),
                extra=extra,
            )

    async def _route_to_destination(
        self, message: MQTTMessage, dest_name: str, route_info: MessageRouteInfo
    ) -> None:
        """Route message to a specific destination"""
        destination = self.destinations.get(dest_name)
        if not destination:
            route_info.results[dest_name] = RouteResult(
                destination=dest_name,
                status=RouteStatus.FAILED,
                processing_time=0.0,
                error="Destination not found",
            )
            return

        start_time = time.monotonic()

        # Try routing with retries
        for attempt in range(self.max_retries + 1):
            try:
                success = await destination.process_message(message)

                processing_time = time.monotonic() - start_time

                if success:
                    route_info.results[dest_name] = RouteResult(
                        destination=dest_name,
                        status=RouteStatus.SUCCESS,
                        processing_time=processing_time,
                        retry_count=attempt,
                    )
                    return
                if attempt < self.max_retries:
                    logger.debug(
                        "event=router.destination_retry destination=%s \
                             attempt=%s message_id=%s",
                        dest_name,
                        attempt + 1,
                        route_info.message_id,
                        extra={
                            **self._log_context,
                            "destination": dest_name,
                            "attempt": attempt + 1,
                            "message_id": route_info.message_id,
                        },
                    )
                    await asyncio.sleep(self.config.get_jittered_backoff_delay(attempt))
                else:
                    route_info.results[dest_name] = RouteResult(
                        destination=dest_name,
                        status=RouteStatus.FAILED,
                        processing_time=processing_time,
                        error="Processing failed after retries",
                        retry_count=attempt,
                    )
                    return

            except Exception as e:
                processing_time = time.monotonic() - start_time

                if attempt < self.max_retries:
                    logger.debug(
                        "event=router.destination_retry_exception destination=%s \
                             attempt=%s message_id=%s error=%s",
                        dest_name,
                        attempt + 1,
                        route_info.message_id,
                        e,
                        extra={
                            **self._log_context,
                            "destination": dest_name,
                            "attempt": attempt + 1,
                            "message_id": route_info.message_id,
                            "error": str(e),
                        },
                    )
                    await asyncio.sleep(self.config.get_jittered_backoff_delay(attempt))
                else:
                    route_info.results[dest_name] = RouteResult(
                        destination=dest_name,
                        status=RouteStatus.FAILED,
                        processing_time=processing_time,
                        error=str(e),
                        retry_count=attempt,
                    )
                    return

    def _extract_charger_id(self, topic: str) -> str:
        """Extract charger ID from MQTT topic"""
        metadata = self.topic_extractor.extract(topic=topic, payload=None)
        return metadata.charger_id if metadata else "unknown"

    @staticmethod
    def _new_message_id() -> str:
        return f"msg_{uuid.uuid4().hex}"

    async def _metrics_loop(self) -> None:
        """Background metrics loop"""
        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(self.config.metrics_interval)

                # Log performance metrics
                metrics = self.get_performance_metrics()
                health = self.get_health_status()

                logger.info(
                    "event=router.metrics routed=%s success_rate=%s",
                    metrics.total_messages_routed,
                    metrics.routing_success_rate,
                    extra={
                        **self._log_context,
                        "performance_metrics": metrics,
                        "health_status": health,
                    },
                )

        except asyncio.CancelledError:
            logger.debug("event=router.metrics_cancelled", extra=self._log_context)
        except Exception as e:
            logger.error(
                "event=router.metrics_failed error=%s",
                e,
                extra=self._log_context,
                exc_info=True,
            )

    def get_performance_metrics(self) -> RouterPerformanceMetrics:
        """Get performance metrics"""
        success_rate = 0
        avg_routing_time = 0

        if self.total_messages_routed > 0:
            success_rate = (
                self.total_successful_routes / self.total_messages_routed
            ) * 100
            avg_routing_time = self.total_routing_time / self.total_messages_routed

        return RouterPerformanceMetrics(
            total_messages_routed=self.total_messages_routed,
            total_successful_routes=self.total_successful_routes,
            total_failed_routes=self.total_failed_routes,
            routing_success_rate=round(success_rate, 2),
            average_routing_time=round(avg_routing_time, 3),
            active_routes=len(self.active_routes),
            total_destinations=len(self.destinations),
            enabled_destinations=len(
                [d for d in self.destinations.values() if d.enabled]
            ),
            destination_metrics=[
                dest.get_metrics() for dest in self.destinations.values()
            ],
        )

    def get_health_status(self) -> RouterHealthStatus:
        """Get health status for monitoring"""
        metrics = self.get_performance_metrics()

        # Determine overall health
        status = HealthStatus.HEALTHY

        # Check routing success rate (only if messages have been processed)
        if self.total_messages_routed == 0:
            status = HealthStatus.HEALTHY  # No messages yet - normal bootstrap state
        elif metrics.routing_success_rate < 95:
            status = HealthStatus.UNHEALTHY
        elif metrics.routing_success_rate < 98:
            status = HealthStatus.DEGRADED

        # Check for too many active routes
        if metrics.active_routes > self.max_concurrent_routes * 0.8:
            status = HealthStatus.UNHEALTHY
        elif metrics.active_routes > self.max_concurrent_routes * 0.5:
            status = HealthStatus.DEGRADED

        # Check destination health
        unhealthy_destinations = [
            dest.name
            for dest in self.destinations.values()
            if dest.get_health_status().status == HealthStatus.UNHEALTHY
        ]

        if unhealthy_destinations:
            status = HealthStatus.DEGRADED

        return RouterHealthStatus(
            status=status,
            messages_per_second=self._calculate_messages_per_second(),
            unhealthy_destinations=unhealthy_destinations,
            performance=metrics,
        )

    def _calculate_messages_per_second(self) -> float:
        """Calculate messages per second rate"""
        if self.total_messages_routed > 0 and self.total_routing_time > 0:
            return round(self.total_messages_routed / self.total_routing_time, 2)
        return 0.0
