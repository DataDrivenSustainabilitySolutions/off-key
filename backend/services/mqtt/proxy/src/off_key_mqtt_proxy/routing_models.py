"""Typed state and metrics produced by MQTT message routing."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from off_key_core.utils.enum import HealthStatus


@dataclass(frozen=True, slots=True)
class DestinationMetrics:
    name: str
    enabled: bool
    message_count: int
    success_count: int
    failure_count: int
    success_rate: float
    average_processing_time: float


@dataclass(frozen=True, slots=True)
class DestinationHealthStatus:
    destination: str
    status: HealthStatus
    metrics: DestinationMetrics


@dataclass(frozen=True, slots=True)
class RouterPerformanceMetrics:
    total_messages_routed: int
    total_successful_routes: int
    total_failed_routes: int
    routing_success_rate: float
    average_routing_time: float
    active_routes: int
    total_destinations: int
    enabled_destinations: int
    destination_metrics: list[DestinationMetrics]


@dataclass(frozen=True, slots=True)
class RouterHealthStatus:
    status: HealthStatus
    messages_per_second: float
    unhealthy_destinations: list[str]
    performance: RouterPerformanceMetrics


class RouteStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class RouteResult:
    destination: str
    status: RouteStatus
    processing_time: float
    error: str | None = None
    retry_count: int = 0


@dataclass(slots=True)
class MessageRouteInfo:
    message_id: str
    topic: str
    charger_id: str
    timestamp: datetime
    destinations: list[str]
    results: dict[str, RouteResult] = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    def get_success_count(self) -> int:
        return sum(
            result.status == RouteStatus.SUCCESS for result in self.results.values()
        )

    def get_failed_destinations(self) -> list[str]:
        return [
            destination
            for destination, result in self.results.items()
            if result.status == RouteStatus.FAILED
        ]

    def get_processing_time(self) -> float:
        completed_at = self.completed_at or datetime.now(UTC)
        return (completed_at - self.started_at).total_seconds()
