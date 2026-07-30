"""
Health Monitor for RADAR Service

Monitors service health and provides metrics collection.
"""

import asyncio
import time
from collections import deque
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from off_key_core.config.logging import get_logging_settings
from off_key_core.config.logs import logger
from off_key_core.schemas.radar import RadarOperationalStatus

from .models import HealthStatus


class HealthMonitor:
    """
    Health monitoring component for RADAR service.

    Responsibilities:
    - Periodic health checks
    - Metrics collection and aggregation
    - Alert generation
    - Health status reporting
    """

    def __init__(
        self,
        health_check_interval: float = 30.0,
        max_processing_times: int = 1000,
    ):
        """
        Initialize health monitor.

        Args:
            health_check_interval: Seconds between health checks
            max_processing_times: Max processing times to track
        """
        self.health_check_interval = health_check_interval
        self.processing_times: deque[float] = deque(maxlen=max_processing_times)

        # Service state
        self.start_time: datetime | None = None
        self.last_health_check = time.time()
        self._shutdown_event: asyncio.Event | None = None
        self._health_check_task: asyncio.Task | None = None

        # Component references (set via set_components)
        self._mqtt_client = None
        self._database_writer = None
        self._detector = None
        self._memory_manager = None
        self._message_processor = None

        self._log_context = {"component": "health_monitor"}
        logging_settings = get_logging_settings()
        self._summary_interval_seconds = logging_settings.LOG_HEARTBEAT_INTERVAL_SECONDS
        self._last_summary_log = 0.0

    def set_components(
        self,
        mqtt_client=None,
        database_writer=None,
        detector=None,
        memory_manager=None,
        message_processor=None,
    ) -> None:
        """
        Set references to components for health checking.

        Args:
            mqtt_client: MQTT client component
            database_writer: Database writer component
            detector: Anomaly detector component
            memory_manager: Memory manager component
            message_processor: Message processor component
        """
        self._mqtt_client = mqtt_client
        self._database_writer = database_writer
        self._detector = detector
        self._memory_manager = memory_manager
        self._message_processor = message_processor

    async def start(self, shutdown_event: asyncio.Event) -> None:
        """
        Start health monitoring.

        Args:
            shutdown_event: Event signaling service shutdown
        """
        self.start_time = datetime.now()
        self._shutdown_event = shutdown_event
        self._health_check_task = asyncio.create_task(self._monitor_loop())
        logger.info("Health monitor started", extra=self._log_context)

    async def stop(self) -> None:
        """Stop health monitoring."""
        if self._health_check_task:
            self._health_check_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._health_check_task
        logger.info("Health monitor stopped", extra=self._log_context)

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        try:
            while self._shutdown_event and not self._shutdown_event.is_set():
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=self.health_check_interval,
                    )
                    break  # Shutdown event was set
                except TimeoutError:
                    await self._perform_health_check()
        except asyncio.CancelledError:
            logger.debug(
                "event=radar.health_monitor_cancelled", extra=self._log_context
            )
        except Exception as e:
            logger.error(
                "event=radar.health_monitor_error error=%s",
                str(e),
                extra=self._log_context,
                exc_info=True,
            )

    async def _perform_health_check(self) -> None:
        """Perform comprehensive health check."""
        try:
            status = self.get_health_status()

            # Log based on status
            if status.status in ["degraded", "failed"]:
                logger.warning(
                    f"Service health: {status.status}", extra=self._log_context
                )
                for alert in status.active_alerts:
                    logger.warning(f"Active alert: {alert}", extra=self._log_context)
            else:
                self._maybe_log_healthy_summary(status)

            # Write metrics if database writer is available
            if self._database_writer:
                await self._database_writer.write_service_metrics(
                    self.build_metrics_snapshot(status)
                )

            self.last_health_check = time.time()

        except Exception as e:
            logger.error(
                "event=radar.health_check_failed error=%s",
                str(e),
                extra=self._log_context,
                exc_info=True,
            )

    def build_metrics_snapshot(
        self, status: HealthStatus | None = None
    ) -> dict[str, Any]:
        """Build the current metrics payload for persistence."""
        return self._build_metrics_dict(status or self.get_health_status())

    def _build_metrics_dict(self, status: HealthStatus) -> dict[str, Any]:
        """Build metrics dictionary for persistence."""
        metrics = status.metrics

        return {
            "total_messages_processed": metrics.get("processed_message_count", 0),
            "total_anomalies_detected": metrics.get("anomaly_count", 0),
            "anomaly_rate": metrics.get("anomaly_rate", 0),
            "avg_processing_time_ms": metrics.get("avg_processing_time_ms", 0),
            "throughput_per_second": metrics.get("throughput_per_second", 0),
            "memory_usage_mb": metrics.get("memory_usage_mb", 0),
            "error_count": metrics.get("error_count", 0),
            "error_rate": metrics.get("error_rate", 0),
            "service_status": status.status,
            "active_alerts": status.active_alerts,
            "operational_status": metrics.get("operational_status"),
        }

    def record_processing_time(self, processing_time: float) -> None:
        """Record a message processing time."""
        self.processing_times.append(processing_time)

    def _calculate_avg_processing_time(self) -> float:
        """Calculate average processing time in milliseconds."""
        if not self.processing_times:
            return 0.0
        return sum(self.processing_times) / len(self.processing_times) * 1000

    def _calculate_throughput(self, message_count: int) -> float:
        """Calculate messages per second throughput."""
        if not self.start_time:
            return 0.0
        uptime = (datetime.now() - self.start_time).total_seconds()
        if uptime <= 0:
            return 0.0
        return message_count / uptime

    def _collect_component_health(self) -> dict[str, Any]:
        """Collect health payloads from the configured runtime components."""
        components: dict[str, Any] = {}
        if self._mqtt_client:
            components["mqtt_client"] = self._mqtt_client.get_health_status()
        if self._database_writer:
            components["database_writer"] = self._database_writer.get_health_status()
        if self._detector:
            components["anomaly_detector"] = self._detector.get_health_info()
        return components

    def _collect_active_alerts(
        self,
        components: dict[str, Any],
        processor_metrics: dict[str, Any],
        memory_usage: float,
    ) -> list[str]:
        """Reduce component and resource health into stable alert identifiers."""
        alerts: list[str] = []
        mqtt_health = components.get("mqtt_client")
        if mqtt_health and mqtt_health.get("status") != "healthy":
            alerts.append(f"mqtt_{mqtt_health.get('reason', 'unknown')}")

        database_health = components.get("database_writer")
        if database_health and database_health.get("status") not in {
            "healthy",
            "disabled",
        }:
            alerts.append(f"database_{database_health.get('reason', 'unknown')}")

        detector_health = components.get("anomaly_detector")
        if detector_health and detector_health.get("state") != "healthy":
            alerts.append(f"detector_{detector_health.get('state')}")

        if (
            self._memory_manager
            and memory_usage > self._memory_manager.max_memory_mb * 0.9
        ):
            alerts.append("high_memory_usage")
        if processor_metrics.get("error_rate", 0) > 0.1:
            alerts.append("high_error_rate")
        return alerts

    def _uptime_seconds(self) -> float:
        if self.start_time is None:
            return 0.0
        return (datetime.now() - self.start_time).total_seconds()

    def _build_health_metrics(
        self,
        *,
        service_status: str,
        components: dict[str, Any],
        processor_metrics: dict[str, Any],
        memory_usage: float,
        uptime: float,
    ) -> dict[str, Any]:
        """Build the health response metrics from one consistent snapshot."""
        message_count = int(processor_metrics.get("message_count", 0) or 0)
        processed_count = int(
            processor_metrics.get("processed_message_count", message_count) or 0
        )
        metrics = {
            "uptime_seconds": uptime,
            "message_count": message_count,
            "processed_message_count": processed_count,
            "anomaly_count": processor_metrics.get("anomaly_count", 0),
            "anomaly_rate": processor_metrics.get("anomaly_rate", 0),
            "error_count": processor_metrics.get("error_count", 0),
            "error_rate": processor_metrics.get("error_rate", 0),
            "last_alignment_status": processor_metrics.get("last_alignment_status"),
            "avg_processing_time_ms": self._calculate_avg_processing_time(),
            "throughput_per_second": self._calculate_throughput(processed_count),
            "memory_usage_mb": memory_usage,
        }
        metrics["operational_status"] = self._build_operational_status(
            service_status=service_status,
            components=components,
            processor_metrics=processor_metrics,
        )
        return metrics

    def get_health_status(self) -> HealthStatus:
        """Get comprehensive health status."""
        components = self._collect_component_health()
        processor_metrics = (
            self._message_processor.get_metrics() if self._message_processor else {}
        )
        memory_usage = (
            self._memory_manager.get_memory_usage() if self._memory_manager else 0.0
        )
        active_alerts = self._collect_active_alerts(
            components,
            processor_metrics,
            memory_usage,
        )

        if self.start_time is None:
            status = "failed"
        elif active_alerts:
            status = "degraded"
        else:
            status = "healthy"

        uptime = self._uptime_seconds()
        metrics = self._build_health_metrics(
            service_status=status,
            components=components,
            processor_metrics=processor_metrics,
            memory_usage=memory_usage,
            uptime=uptime,
        )

        return HealthStatus(
            status=status,
            timestamp=datetime.now(),
            components=components,
            metrics=metrics,
            active_alerts=active_alerts,
            uptime_seconds=uptime,
        )

    def _build_operational_status(
        self,
        *,
        service_status: str,
        components: dict[str, Any],
        processor_metrics: dict[str, Any],
    ) -> dict[str, Any]:
        detector_health = components.get("anomaly_detector", {}) or {}
        detector_stats = detector_health.get("primary_service_stats", {}) or {}
        message_count = int(processor_metrics.get("message_count", 0) or 0)
        processed_count = int(
            processor_metrics.get("processed_message_count", message_count) or 0
        )
        last_alignment_status = processor_metrics.get("last_alignment_status")

        stage = "waiting_for_data"
        detail = None
        progress = None
        error = detector_stats.get("training_error")

        detector_state = detector_health.get("state")
        if service_status == "failed" or detector_state == "failed":
            stage = "failed"
            detail = "RADAR runtime failed"
        elif detector_stats.get("state") == "failed":
            stage = "failed"
            detail = "Static baseline training failed"
        elif service_status == "degraded" or detector_state == "degraded":
            stage = "degraded"
            detail = "RADAR runtime is degraded"
        elif processed_count <= 0:
            stage = "waiting_for_data"
            detail = (
                "Waiting for aligned sensor data"
                if last_alignment_status
                and last_alignment_status != "direct_pass_through"
                else "Waiting for telemetry"
            )
        elif detector_stats.get("strategy") == "static_baseline":
            stage, detail, progress = self._static_operational_stage(detector_stats)
        else:
            stage = "operational"

        return RadarOperationalStatus(
            stage=stage,
            detail=detail,
            progress=progress,
            message_count=message_count,
            processed_message_count=processed_count,
            last_alignment_status=last_alignment_status,
            error=error,
            updated_at=datetime.now(UTC),
            is_stale=False,
        ).model_dump(mode="json", exclude_none=True)

    @staticmethod
    def _static_operational_stage(
        detector_stats: dict[str, Any],
    ) -> tuple[str, str | None, dict[str, int] | None]:
        state = detector_stats.get("state")
        if state == "collecting":
            current = int(detector_stats.get("training_collected_samples", 0) or 0)
            target = int(detector_stats.get("training_window_size", 1) or 1)
            return (
                "collecting_training",
                f"{current}/{target} training samples",
                {"current": current, "target": max(target, 1)},
            )
        if state == "calibrating":
            current = int(detector_stats.get("calibration_collected_samples", 0) or 0)
            target = int(detector_stats.get("calibration_window_size", 1) or 1)
            return (
                "collecting_calibration",
                f"{current}/{target} calibration samples",
                {"current": current, "target": max(target, 1)},
            )
        if state == "training":
            return "training", "Fitting static baseline", None
        if state == "ready":
            return "operational", None, None
        if state == "failed":
            return "failed", "Static baseline training failed", None
        return "waiting_for_data", "Waiting for telemetry", None

    def _maybe_log_healthy_summary(self, status: HealthStatus) -> None:
        now = time.time()
        if now - self._last_summary_log < self._summary_interval_seconds:
            return

        metrics = status.metrics
        logger.info(
            (
                "event=radar.health_summary status=%s message_count=%s "
                "anomaly_rate=%.4f error_rate=%.4f throughput=%.2f "
                "memory_mb=%.2f"
            ),
            status.status,
            metrics.get("message_count", 0),
            metrics.get("anomaly_rate", 0.0),
            metrics.get("error_rate", 0.0),
            metrics.get("throughput_per_second", 0.0),
            metrics.get("memory_usage_mb", 0.0),
            extra=self._log_context,
        )
        self._last_summary_log = now
