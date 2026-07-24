"""Resilience and circuit-breaker handling for anomaly detection."""

import logging
import time
from collections import deque
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol

import numpy as np

from .models import AnomalyResult


class ServiceState(Enum):
    """Runtime health of the anomaly detector."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class DetectionService(Protocol):
    """Detector operations required by the resilience wrapper."""

    def process_data_point(
        self,
        data: dict[str, float],
        topic: str | None = None,
        charger_id: str | None = None,
    ) -> AnomalyResult: ...

    def get_model_info(self) -> dict[str, Any]: ...


class ResilientAnomalyDetector:
    """Run a detector behind fallback and circuit-breaker protection."""

    def __init__(
        self,
        primary_service: DetectionService,
        fallback_service: DetectionService | None = None,
    ) -> None:
        self.primary_service = primary_service
        self.fallback_service = fallback_service
        self.state = ServiceState.HEALTHY
        self.error_count = 0
        self.error_window = 100
        self.error_threshold = 0.1
        self.last_errors: deque[float] = deque(maxlen=self.error_window)
        self.circuit_breaker_timeout = 300.0
        self.circuit_breaker_opened_at: float | None = None
        self.start_time = time.monotonic()
        self.logger = logging.getLogger(__name__)

    @property
    def circuit_breaker_open(self) -> bool:
        return self.circuit_breaker_opened_at is not None

    async def stop(self) -> None:
        """Release resources held by wrapped detector services."""
        for service in (self.primary_service, self.fallback_service):
            shutdown = getattr(service, "shutdown", None)
            if callable(shutdown):
                shutdown()

    def process_with_resilience(
        self,
        data: dict[str, float],
        topic: str | None = None,
        charger_id: str | None = None,
    ) -> AnomalyResult:
        """Process one point, falling back when the primary detector fails."""
        try:
            if self._should_use_circuit_breaker():
                return self._fallback_processing(
                    data, topic, charger_id, "circuit_breaker"
                )

            result = self.primary_service.process_data_point(data, topic, charger_id)
            self._record_success()
            return result
        except Exception as error:
            self._record_error(error)
            return self._fallback_processing(data, topic, charger_id, str(error))

    def _fallback_processing(
        self,
        data: dict[str, float],
        topic: str | None,
        charger_id: str | None,
        reason: str,
    ) -> AnomalyResult:
        self.logger.warning("event=radar.fallback_processing reason=%s", reason)

        try:
            if self.fallback_service is not None:
                result = self.fallback_service.process_data_point(
                    data, topic, charger_id
                )
                result.context = result.context or {}
                result.context.update(
                    fallback_reason=reason,
                    model_used="fallback",
                )
                return result

            score = self._simple_statistical_anomaly_score(data)
            return AnomalyResult(
                anomaly_score=score,
                is_anomaly=False,
                severity="unknown",
                timestamp=datetime.now(UTC),
                model_info={"model_used": "statistical"},
                raw_data=data,
                topic=topic,
                charger_id=charger_id,
                context={
                    "fallback_reason": reason,
                    "model_used": "statistical",
                    "service_state": ServiceState.DEGRADED.value,
                },
            )
        except Exception as error:
            self.logger.exception(
                "event=radar.fallback_processing_failed error=%s", error
            )
            return AnomalyResult(
                anomaly_score=0.0,
                is_anomaly=False,
                severity="unknown",
                timestamp=datetime.now(UTC),
                model_info={"error": str(error), "model_used": "none"},
                raw_data=data,
                topic=topic,
                charger_id=charger_id,
                context={
                    "error": str(error),
                    "fallback_reason": reason,
                    "service_state": ServiceState.FAILED.value,
                },
            )

    def _simple_statistical_anomaly_score(self, data: dict[str, float]) -> float:
        """Return a diagnostic score that never directly raises an alarm."""
        try:
            current_mean = float(np.mean(list(data.values())))
            if not hasattr(self, "_running_mean"):
                self._running_mean = current_mean
                self._running_std = 1.0
                self._count = 1
                return 0.0

            self._count += 1
            alpha = 1.0 / min(self._count, 100)
            self._running_mean = (1 - alpha) * self._running_mean + alpha * current_mean
            deviation = abs(current_mean - self._running_mean)
            return min(deviation / (self._running_std + 1e-8), 1.0)
        except (ValueError, TypeError, ZeroDivisionError):
            return 0.0

    def _record_error(self, error: Exception) -> None:
        self.error_count += 1
        self.last_errors.append(time.monotonic())
        if len(self.last_errors) / self.error_window > self.error_threshold:
            self._open_circuit_breaker()
        self.logger.error("event=radar.model_error error=%s", error)

    def _record_success(self) -> None:
        if self.circuit_breaker_open:
            self._close_circuit_breaker()

    def _should_use_circuit_breaker(self) -> bool:
        opened_at = self.circuit_breaker_opened_at
        if opened_at is None:
            return False
        if time.monotonic() - opened_at > self.circuit_breaker_timeout:
            self._close_circuit_breaker()
            return False
        return True

    def _open_circuit_breaker(self) -> None:
        self.circuit_breaker_opened_at = time.monotonic()
        self.state = ServiceState.DEGRADED
        self.logger.warning("Circuit breaker opened - using fallback processing")

    def _close_circuit_breaker(self) -> None:
        self.circuit_breaker_opened_at = None
        self.state = ServiceState.HEALTHY
        self.logger.info("Circuit breaker closed - resuming normal processing")

    def get_service_state(self) -> ServiceState:
        return self.state

    def get_health_info(self) -> dict[str, Any]:
        refresh_background_state = getattr(
            self.primary_service, "refresh_background_state", None
        )
        if callable(refresh_background_state):
            refresh_background_state()
        return {
            "state": self.state.value,
            "circuit_breaker_open": self.circuit_breaker_open,
            "error_count": self.error_count,
            "recent_error_rate": len(self.last_errors) / self.error_window,
            "primary_service_stats": self.primary_service.get_model_info(),
            "uptime_seconds": time.monotonic() - self.start_time,
        }
