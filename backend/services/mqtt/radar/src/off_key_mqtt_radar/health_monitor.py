"""
Health Monitor for RADAR Service

Monitors service health and provides metrics collection.
"""

import asyncio
import time
from collections import deque
from datetime import datetime
from typing import Optional, Dict, Any, List, Deque

from off_key_core.config.logs import logger

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
        self.processing_times: Deque[float] = deque(maxlen=max_processing_times)

        # Service state
        self.start_time: Optional[datetime] = None
        self.last_health_check = time.time()
        self._shutdown_event: Optional[asyncio.Event] = None
        self._health_check_task: Optional[asyncio.Task] = None

        # Component references (set via set_components)
        self._mqtt_client = None
        self._database_writer = None
        self._detector = None
        self._memory_manager = None
        self._message_processor = None

        self._log_context = {"component": "health_monitor"}

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
        if self._health_check_task is not None:
            logger.warning("Health monitor already started", extra=self._log_context)
            return
        self.start_time = datetime.now()
        self._shutdown_event = shutdown_event
        self._health_check_task = asyncio.create_task(self._monitor_loop())
        logger.info("Health monitor started", extra=self._log_context)

    async def stop(self) -> None:
        """Stop health monitoring."""
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
            self._health_check_task = None
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
                except asyncio.TimeoutError:
                    await self._perform_health_check()
        except asyncio.CancelledError:
            logger.info("Health monitor cancelled", extra=self._log_context)
        except Exception as e:
            logger.error(f"Health monitor error: {e}", extra=self._log_context)

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
                logger.debug(
                    f"Service health: {status.status}", extra=self._log_context
                )

            # Write metrics if database writer is available
            if self._database_writer and status.status != "failed":
                metrics = self._build_metrics_dict(status)
                await self._database_writer.write_service_metrics(metrics)

            self.last_health_check = time.time()

        except Exception as e:
            logger.error(f"Health check failed: {e}", extra=self._log_context)

    def _build_metrics_dict(self, status: HealthStatus) -> Dict[str, Any]:
        """Build metrics dictionary for persistence."""
        processor_metrics = (
            self._message_processor.get_metrics() if self._message_processor else {}
        )

        return {
            "total_messages_processed": processor_metrics.get("message_count", 0),
            "total_anomalies_detected": processor_metrics.get("anomaly_count", 0),
            "anomaly_rate": processor_metrics.get("anomaly_rate", 0),
            "avg_processing_time_ms": self._calculate_avg_processing_time(),
            "throughput_per_second": self._calculate_throughput(
                processor_metrics.get("message_count", 0)
            ),
            "memory_usage_mb": (
                self._memory_manager.get_memory_usage() if self._memory_manager else 0
            ),
            "error_count": processor_metrics.get("error_count", 0),
            "error_rate": processor_metrics.get("error_rate", 0),
            "service_status": status.status,
            "active_alerts": status.active_alerts,
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

    def get_health_status(self) -> HealthStatus:
        """Get comprehensive health status."""
        components: Dict[str, Any] = {}
        active_alerts: List[str] = []

        # Check MQTT client
        if self._mqtt_client:
            mqtt_health = self._mqtt_client.get_health_status()
            components["mqtt_client"] = mqtt_health
            if mqtt_health.get("status") != "healthy":
                active_alerts.append(f"mqtt_{mqtt_health.get('reason', 'unknown')}")

        # Check database writer
        if self._database_writer:
            db_health = self._database_writer.get_health_status()
            components["database_writer"] = db_health
            if db_health.get("status") not in ("healthy", "disabled"):
                active_alerts.append(f"database_{db_health.get('reason', 'unknown')}")

        # Check anomaly detector
        if self._detector:
            detector_health = self._detector.get_health_info()
            components["anomaly_detector"] = detector_health
            if detector_health.get("state") != "healthy":
                active_alerts.append(f"detector_{detector_health.get('state')}")

        # Check memory usage
        if self._memory_manager:
            memory_usage = self._memory_manager.get_memory_usage()
            if memory_usage > self._memory_manager.max_memory_mb * 0.9:
                active_alerts.append("high_memory_usage")

        # Check error rate
        if self._message_processor:
            metrics = self._message_processor.get_metrics()
            if metrics.get("error_rate", 0) > 0.1:
                active_alerts.append("high_error_rate")

        # Determine overall status
        is_running = self.start_time is not None
        if not is_running:
            status = "failed"
        elif active_alerts:
            status = "degraded"
        else:
            status = "healthy"

        # Calculate metrics
        uptime = 0.0
        if self.start_time:
            uptime = (datetime.now() - self.start_time).total_seconds()

        processor_metrics = (
            self._message_processor.get_metrics() if self._message_processor else {}
        )

        metrics = {
            "uptime_seconds": uptime,
            "message_count": processor_metrics.get("message_count", 0),
            "anomaly_count": processor_metrics.get("anomaly_count", 0),
            "anomaly_rate": processor_metrics.get("anomaly_rate", 0),
            "error_count": processor_metrics.get("error_count", 0),
            "error_rate": processor_metrics.get("error_rate", 0),
            "avg_processing_time_ms": self._calculate_avg_processing_time(),
            "throughput_per_second": self._calculate_throughput(
                processor_metrics.get("message_count", 0)
            ),
            "memory_usage_mb": (
                self._memory_manager.get_memory_usage() if self._memory_manager else 0
            ),
        }

        return HealthStatus(
            status=status,
            timestamp=datetime.now(),
            components=components,
            metrics=metrics,
            active_alerts=active_alerts,
            uptime_seconds=uptime,
        )
