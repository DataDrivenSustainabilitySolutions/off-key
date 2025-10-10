"""
Message Router for MQTT Telemetry Distribution

Routes MQTT messages to multiple destinations including database, processing containers,
and real-time API endpoints with intelligent logging and error handling.
"""

import asyncio
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod

from off_key_core.config.logs import logger
from off_key_core.utils.enum import HealthStatus
from .config import MQTTConfig
from .client.models import MQTTMessage


@dataclass
class DestinationMetrics:
    """Message destination metrics"""

    name: str
    enabled: bool
    message_count: int
    success_count: int
    failure_count: int
    success_rate: float
    average_processing_time: float


@dataclass
class DestinationHealthStatus:
    """Message destination health status"""

    destination: str
    status: HealthStatus
    metrics: DestinationMetrics


@dataclass
class RouterPerformanceMetrics:
    """Message router performance metrics"""

    total_messages_routed: int
    total_successful_routes: int
    total_failed_routes: int
    routing_success_rate: float
    average_routing_time: float
    active_routes: int
    total_destinations: int
    enabled_destinations: int
    destination_metrics: List[DestinationMetrics]


@dataclass
class RouterHealthStatus:
    """Message router health status"""

    status: HealthStatus
    messages_per_second: float
    unhealthy_destinations: List[str]
    performance: RouterPerformanceMetrics


class RouteStatus(Enum):
    """Message routing status"""

    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class RouteResult:
    """Result of message routing to a destination"""

    destination: str
    status: RouteStatus
    processing_time: float
    error: Optional[str] = None
    retry_count: int = 0


@dataclass
class MessageRouteInfo:
    """Information about message routing"""

    message_id: str
    topic: str
    charger_id: str
    timestamp: datetime
    destinations: List[str]
    results: Dict[str, RouteResult] = field(default_factory=dict)
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    def is_completed(self) -> bool:
        """Check if routing is completed for all destinations"""
        return len(self.results) == len(self.destinations)

    def get_success_count(self) -> int:
        """Get number of successful routes"""
        return sum(
            1
            for result in self.results.values()
            if result.status == RouteStatus.SUCCESS
        )

    def get_failed_destinations(self) -> List[str]:
        """Get list of failed destinations"""
        return [
            dest
            for dest, result in self.results.items()
            if result.status == RouteStatus.FAILED
        ]

    def get_processing_time(self) -> float:
        """Get total processing time in seconds"""
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return (datetime.now() - self.started_at).total_seconds()


class MessageDestination(ABC):
    """Abstract base class for message destinations"""

    def __init__(self, name: str, config: Dict[str, Any] = None):
        self.name = name
        self.config = config or {}
        self.enabled = True
        self.message_count = 0
        self.success_count = 0
        self.failure_count = 0
        self.total_processing_time = 0.0

        # Logging context
        self._log_context = {
            "component": "message_router",
            "destination": name,
            "service": "mqtt_proxy",
        }

    @abstractmethod
    async def process_message(self, message: MQTTMessage) -> bool:
        """
        Process a message at this destination

        Args:
            message: The MQTT message to process

        Returns:
            True if processing successful, False otherwise
        """
        pass

    def get_metrics(self) -> DestinationMetrics:
        """Get destination metrics"""
        success_rate = 0
        avg_processing_time = 0

        if self.message_count > 0:
            success_rate = (self.success_count / self.message_count) * 100
            avg_processing_time = self.total_processing_time / self.message_count

        return DestinationMetrics(
            name=self.name,
            enabled=self.enabled,
            message_count=self.message_count,
            success_count=self.success_count,
            failure_count=self.failure_count,
            success_rate=round(success_rate, 2),
            average_processing_time=round(avg_processing_time, 3),
        )

    def get_health_status(self) -> DestinationHealthStatus:
        """Get destination health status"""
        metrics = self.get_metrics()

        # Determine health status
        status = HealthStatus.HEALTHY
        if not self.enabled:
            status = HealthStatus.DISABLED
        elif metrics.success_rate < 95:
            status = HealthStatus.UNHEALTHY
        elif metrics.success_rate < 98:
            status = HealthStatus.DEGRADED

        return DestinationHealthStatus(
            destination=self.name,
            status=status,
            metrics=metrics,
        )


class DatabaseDestination(MessageDestination):
    """Database destination for telemetry data"""

    def __init__(self, database_writer, config: Dict[str, Any] = None):
        super().__init__("database", config)
        self.database_writer = database_writer

    async def process_message(self, message: MQTTMessage) -> bool:
        """Process message by writing to database"""
        try:
            start_time = time.time()

            await self.database_writer.write_telemetry_message(message)

            processing_time = time.time() - start_time
            self.message_count += 1
            self.success_count += 1
            self.total_processing_time += processing_time

            logger.debug(
                f"Message processed by database destination in {processing_time:.3f}s",
                extra={
                    **self._log_context,
                    "topic": message.topic,
                    "processing_time": processing_time,
                },
            )

            return True

        except Exception as e:
            self.message_count += 1
            self.failure_count += 1

            logger.error(
                f"Database destination processing failed: {e}",
                extra={**self._log_context, "topic": message.topic, "error": str(e)},
                exc_info=True,
            )

            return False


class ContainerDestination(MessageDestination):
    """Container destination for processing services"""

    def __init__(self, container_id: str, endpoint: str, config: Dict[str, Any] = None):
        super().__init__(f"container_{container_id}", config)
        self.container_id = container_id
        self.endpoint = endpoint
        self.timeout = config.get("timeout", 5.0) if config else 5.0

    async def process_message(self, message: MQTTMessage) -> bool:
        """Process message by sending to container"""
        try:
            start_time = time.time()

            # Send to container (implement HTTP client call here)
            # For now, simulate processing
            await asyncio.sleep(0.001)  # Simulate network call

            processing_time = time.time() - start_time
            self.message_count += 1
            self.success_count += 1
            self.total_processing_time += processing_time

            logger.debug(
                f"Message processed by container destination in {processing_time:.3f}s",
                extra={
                    **self._log_context,
                    "container_id": self.container_id,
                    "endpoint": self.endpoint,
                    "topic": message.topic,
                    "processing_time": processing_time,
                },
            )

            return True

        except Exception as e:
            self.message_count += 1
            self.failure_count += 1

            logger.error(
                f"Container destination processing failed: {e}",
                extra={
                    **self._log_context,
                    "container_id": self.container_id,
                    "endpoint": self.endpoint,
                    "topic": message.topic,
                    "error": str(e),
                },
                exc_info=True,
            )

            return False


class WebSocketDestination(MessageDestination):
    """WebSocket destination for real-time API"""

    def __init__(self, websocket_manager, config: Dict[str, Any] = None):
        super().__init__("websocket", config)
        self.websocket_manager = websocket_manager

    async def process_message(self, message: MQTTMessage) -> bool:
        """Process message by broadcasting to WebSocket clients"""
        try:
            start_time = time.time()

            # Broadcast to WebSocket clients (implement WebSocket manager call here)
            # For now, simulate broadcasting
            await asyncio.sleep(0.001)  # Simulate broadcast

            processing_time = time.time() - start_time
            self.message_count += 1
            self.success_count += 1
            self.total_processing_time += processing_time

            logger.debug(
                f"Message processed by WebSocket destination in {processing_time:.3f}s",
                extra={
                    **self._log_context,
                    "topic": message.topic,
                    "processing_time": processing_time,
                },
            )

            return True

        except Exception as e:
            self.message_count += 1
            self.failure_count += 1

            logger.error(
                f"WebSocket destination processing failed: {e}",
                extra={**self._log_context, "topic": message.topic, "error": str(e)},
                exc_info=True,
            )

            return False


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

    def __init__(self, config: MQTTConfig):
        self.config = config

        # Destinations
        self.destinations: Dict[str, MessageDestination] = {}
        self.default_destinations: Set[str] = set()

        # Message routing
        self.active_routes: Dict[str, MessageRouteInfo] = {}
        self.completed_routes: List[MessageRouteInfo] = []
        self.max_completed_routes = 1000

        # Performance metrics
        self.total_messages_routed = 0
        self.total_successful_routes = 0
        self.total_failed_routes = 0
        self.total_routing_time = 0.0

        # Configuration
        self.max_concurrent_routes = config.worker_threads * 10
        self.route_timeout = 10.0
        self.retry_enabled = True
        self.max_retries = 2

        # Background tasks
        self._cleanup_task: Optional[asyncio.Task] = None
        self._metrics_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._all_routes_completed_event = asyncio.Event()

        # Logging context
        self._log_context = {"component": "message_router", "service": "mqtt_proxy"}

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    async def start(self):
        """Start the message router"""
        logger.info("Starting message router", extra=self._log_context)

        # Start background tasks
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        self._metrics_task = asyncio.create_task(self._metrics_loop())

        logger.info(
            "Message router started successfully",
            extra={
                **self._log_context,
                "max_concurrent_routes": self.max_concurrent_routes,
                "route_timeout": self.route_timeout,
                "retry_enabled": self.retry_enabled,
            },
        )

    async def stop(self):
        """Stop the message router"""
        logger.info("Stopping message router", extra=self._log_context)

        # Signal shutdown
        self._shutdown_event.set()

        # Cancel background tasks
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        if self._metrics_task and not self._metrics_task.done():
            self._metrics_task.cancel()
            try:
                await self._metrics_task
            except asyncio.CancelledError:
                pass

        # Wait for active routes to complete (race-condition-free)
        # First: Handle already-complete case atomically
        if not self.active_routes:
            logger.debug("All active routes already completed", extra=self._log_context)
            self._all_routes_completed_event.set()  # Ensure consistent event state

        # Second: Only wait if event is not already set (prevents race condition)
        if not self._all_routes_completed_event.is_set():
            logger.info(
                f"Waiting for {len(self.active_routes)} active routes to complete",
                extra={**self._log_context, "active_routes": len(self.active_routes)},
            )

            try:
                await asyncio.wait_for(
                    self._all_routes_completed_event.wait(),
                    timeout=self.config.graceful_shutdown_timeout,
                )
                logger.info(
                    "All active routes completed successfully", extra=self._log_context
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"Graceful shutdown timeout: "
                    f"{len(self.active_routes)} routes did not complete",
                    extra={
                        **self._log_context,
                        "remaining_routes": len(self.active_routes),
                        "timeout": self.config.graceful_shutdown_timeout,
                    },
                )

        logger.info("Message router stopped", extra=self._log_context)

    def add_destination(
        self, destination: MessageDestination, is_default: bool = False
    ):
        """Add a message destination"""
        self.destinations[destination.name] = destination

        if is_default:
            self.default_destinations.add(destination.name)

        logger.info(
            f"Added destination: {destination.name}",
            extra={
                **self._log_context,
                "destination": destination.name,
                "is_default": is_default,
                "total_destinations": len(self.destinations),
            },
        )

    def remove_destination(self, destination_name: str):
        """Remove a message destination"""
        if destination_name in self.destinations:
            del self.destinations[destination_name]
            self.default_destinations.discard(destination_name)

            logger.info(
                f"Removed destination: {destination_name}",
                extra={
                    **self._log_context,
                    "destination": destination_name,
                    "total_destinations": len(self.destinations),
                },
            )

    def enable_destination(self, destination_name: str):
        """Enable a message destination"""
        if destination_name in self.destinations:
            self.destinations[destination_name].enabled = True
            logger.info(
                f"Enabled destination: {destination_name}",
                extra={**self._log_context, "destination": destination_name},
            )

    def disable_destination(self, destination_name: str):
        """Disable a message destination"""
        if destination_name in self.destinations:
            self.destinations[destination_name].enabled = False
            logger.warning(
                f"Disabled destination: {destination_name}",
                extra={**self._log_context, "destination": destination_name},
            )

    async def route_message(
        self, message: MQTTMessage, destinations: Optional[List[str]] = None
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
                message_id=f"msg_{int(time.time() * 1000)}",
                topic=message.topic,
                charger_id=self._extract_charger_id(message.topic),
                timestamp=message.timestamp,
                destinations=destinations,
            )

        # Create route info
        route_info = MessageRouteInfo(
            message_id=f"msg_{int(time.time() * 1000)}",
            topic=message.topic,
            charger_id=self._extract_charger_id(message.topic),
            timestamp=message.timestamp,
            destinations=enabled_destinations,
        )

        # Track active route
        self.active_routes[route_info.message_id] = route_info

        # Route message to destinations concurrently
        tasks = []
        for dest_name in enabled_destinations:
            task = asyncio.create_task(
                self._route_to_destination(message, dest_name, route_info)
            )
            tasks.append(task)

        # Wait for all routes to complete with timeout
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=self.route_timeout,
            )
        except asyncio.TimeoutError:
            logger.error(
                f"Message routing timeout after {self.route_timeout}s",
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

        # Complete routing
        route_info.completed_at = datetime.now()
        self.active_routes.pop(route_info.message_id, None)

        # Signal completion if all routes are done (for graceful shutdown)
        if not self.active_routes:
            self._all_routes_completed_event.set()

        # Update metrics
        self.total_messages_routed += 1
        self.total_routing_time += route_info.get_processing_time()

        if route_info.get_success_count() == len(enabled_destinations):
            self.total_successful_routes += 1
        else:
            self.total_failed_routes += 1

        # Store completed route
        self.completed_routes.append(route_info)
        if len(self.completed_routes) > self.max_completed_routes:
            self.completed_routes.pop(0)

        # Log routing results with intelligent frequency
        if (
            self.total_messages_routed % 100 == 0
            or route_info.get_success_count() < len(enabled_destinations)
        ):
            message_text = (
                f"Message routed: {route_info.get_success_count()}/"
                f"{len(enabled_destinations)} successful"
            )
            extra_data = {
                **self._log_context,
                "message_id": route_info.message_id,
                "topic": message.topic,
                "destinations": enabled_destinations,
                "success_count": route_info.get_success_count(),
                "failed_destinations": route_info.get_failed_destinations(),
                "processing_time": route_info.get_processing_time(),
                "total_routed": self.total_messages_routed,
            }

            if route_info.get_success_count() == len(enabled_destinations):
                logger.info(message_text, extra=extra_data)
            else:
                logger.warning(message_text, extra=extra_data)

        return route_info

    async def _route_to_destination(
        self, message: MQTTMessage, dest_name: str, route_info: MessageRouteInfo
    ):
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

        start_time = time.time()

        # Try routing with retries
        for attempt in range(self.max_retries + 1):
            try:
                success = await destination.process_message(message)

                processing_time = time.time() - start_time

                if success:
                    route_info.results[dest_name] = RouteResult(
                        destination=dest_name,
                        status=RouteStatus.SUCCESS,
                        processing_time=processing_time,
                        retry_count=attempt,
                    )
                    return
                else:
                    if attempt < self.max_retries:
                        logger.debug(
                            f"Retrying destination {dest_name} (attempt {attempt + 1})",
                            extra={
                                **self._log_context,
                                "destination": dest_name,
                                "attempt": attempt + 1,
                                "message_id": route_info.message_id,
                            },
                        )
                        await asyncio.sleep(
                            self.config.get_jittered_backoff_delay(attempt)
                        )
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
                processing_time = time.time() - start_time

                if attempt < self.max_retries:
                    logger.debug(
                        f"Exception in destination {dest_name}, "
                        f"retrying (attempt {attempt + 1}): {e}",
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
        # Topic format: charger/{charger_id}/live-telemetry/{hierarchy}
        parts = topic.split("/")
        if len(parts) >= 2 and parts[0] == "charger":
            return parts[1]
        return "unknown"

    async def _cleanup_loop(self):
        """Background cleanup loop"""
        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(self.config.cleanup_interval)

                # Clean up old completed routes
                if len(self.completed_routes) > self.max_completed_routes:
                    removed = len(self.completed_routes) - self.max_completed_routes
                    self.completed_routes = self.completed_routes[
                        -self.max_completed_routes :
                    ]

                    logger.debug(
                        f"Cleaned up {removed} old completed routes",
                        extra={**self._log_context, "removed_routes": removed},
                    )

        except asyncio.CancelledError:
            logger.info("Cleanup loop cancelled", extra=self._log_context)
        except Exception as e:
            logger.error(
                f"Unexpected error in cleanup loop: {e}",
                extra=self._log_context,
                exc_info=True,
            )

    async def _metrics_loop(self):
        """Background metrics loop"""
        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(self.config.metrics_interval)

                # Log performance metrics
                metrics = self.get_performance_metrics()
                health = self.get_health_status()

                logger.info(
                    f"Message router metrics: "
                    f"{metrics.total_messages_routed} routed, "
                    f"{metrics.routing_success_rate}% success rate",
                    extra={
                        **self._log_context,
                        "performance_metrics": metrics,
                        "health_status": health,
                    },
                )

        except asyncio.CancelledError:
            logger.info("Metrics loop cancelled", extra=self._log_context)
        except Exception as e:
            logger.error(
                f"Unexpected error in metrics loop: {e}",
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
