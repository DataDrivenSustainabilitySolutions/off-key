"""
Health Monitoring and Metrics for MQTT Proxy Service

Comprehensive health monitoring, metrics collection, and alerting system with
intelligent logging and performance tracking.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import deque, defaultdict

from fastapi import FastAPI, HTTPException

from ...core.logs import logger
from .config import MQTTConfig


class HealthStatus(Enum):
    """Health status levels"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CRITICAL = "critical"


@dataclass
class HealthMetric:
    """Individual health metric"""

    name: str
    value: float
    status: HealthStatus
    threshold_warning: float
    threshold_critical: float
    unit: str = ""
    description: str = ""
    timestamp: datetime = field(default_factory=datetime.now)

    def is_healthy(self) -> bool:
        """Check if metric is healthy"""
        return self.status == HealthStatus.HEALTHY


@dataclass
class ComponentHealth:
    """Health status for a service component"""

    component_name: str
    status: HealthStatus
    metrics: Dict[str, HealthMetric] = field(default_factory=dict)
    last_updated: datetime = field(default_factory=datetime.now)
    error_message: Optional[str] = None

    def add_metric(self, metric: HealthMetric):
        """Add a metric to this component"""
        self.metrics[metric.name] = metric
        self.last_updated = datetime.now()

        # Update component status based on worst metric
        if metric.status == HealthStatus.CRITICAL:
            self.status = HealthStatus.CRITICAL
        elif (
            metric.status == HealthStatus.UNHEALTHY
            and self.status != HealthStatus.CRITICAL
        ):
            self.status = HealthStatus.UNHEALTHY
        elif metric.status == HealthStatus.DEGRADED and self.status in [
            HealthStatus.HEALTHY
        ]:
            self.status = HealthStatus.DEGRADED


class HealthMonitor:
    """
    Comprehensive health monitoring system for MQTT proxy service

    Features:
    - Multi-component health tracking
    - Threshold-based alerting
    - Performance metrics collection
    - Health history and trends
    - Intelligent logging with context
    - REST API for health checks
    - Automated recovery actions
    """

    def __init__(self, config: MQTTConfig):
        self.config = config

        # Health tracking
        self.components: Dict[str, ComponentHealth] = {}
        self.overall_status = HealthStatus.HEALTHY
        self.health_history: deque = deque(maxlen=1000)

        # Metrics collection
        self.metrics_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self.performance_counters: Dict[str, int] = defaultdict(int)
        self.timing_data: Dict[str, List[float]] = defaultdict(list)

        # Alerting
        self.alert_handlers: List[Callable] = []
        self.alert_cooldown: Dict[str, datetime] = {}
        self.alert_cooldown_duration = timedelta(minutes=5)

        # Background tasks
        self._monitor_task: Optional[asyncio.Task] = None
        self._metrics_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        # FastAPI app for health endpoints
        self.app = FastAPI(title="MQTT Proxy Health Monitor")
        self._setup_health_endpoints()

        # Service start time
        self.start_time = datetime.now()

        # Logging context
        self._log_context = {"component": "health_monitor", "service": "mqtt_proxy"}

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()

    def _setup_health_endpoints(self):
        """Set up FastAPI health check endpoints"""

        @self.app.get("/health")
        async def health_check():
            """Main health check endpoint"""
            return self.get_health_status()

        @self.app.get("/health/live")
        async def liveness_check():
            """Kubernetes liveness probe"""
            return {"status": "alive", "timestamp": datetime.now().isoformat()}

        @self.app.get("/health/ready")
        async def readiness_check():
            """Kubernetes readiness probe"""
            overall_health = self.get_health_status()

            if overall_health["status"] in ["healthy", "degraded"]:
                return {"status": "ready", "timestamp": datetime.now().isoformat()}
            else:
                raise HTTPException(
                    status_code=503,
                    detail={"status": "not_ready", "reason": overall_health["status"]},
                )

        @self.app.get("/health/metrics")
        async def metrics_endpoint():
            """Detailed metrics endpoint"""
            return self.get_detailed_metrics()

        @self.app.get("/health/components")
        async def components_endpoint():
            """Component health details"""
            return self.get_component_health()

        @self.app.get("/health/history")
        async def history_endpoint():
            """Health history endpoint"""
            return self.get_health_history()

    async def start(self):
        """Start the health monitor"""
        logger.info("Starting health monitor", extra=self._log_context)

        # Initialize components
        self._initialize_components()

        # Start background tasks
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        self._metrics_task = asyncio.create_task(self._metrics_loop())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        logger.info(
            "Health monitor started successfully",
            extra={
                **self._log_context,
                "components": list(self.components.keys()),
                "check_interval": self.config.health_check_interval,
            },
        )

    async def stop(self):
        """Stop the health monitor"""
        logger.info("Stopping health monitor", extra=self._log_context)

        # Signal shutdown
        self._shutdown_event.set()

        # Cancel background tasks
        tasks = [self._monitor_task, self._metrics_task, self._cleanup_task]
        for task in tasks:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        logger.info("Health monitor stopped", extra=self._log_context)

    def _initialize_components(self):
        """Initialize component health tracking"""
        components = [
            "api_key_auth",
            "mqtt_client",
            "database_writer",
            "message_router",
            "charger_discovery",
        ]

        for component in components:
            self.components[component] = ComponentHealth(
                component_name=component, status=HealthStatus.HEALTHY
            )

    def register_component(self, component_name: str, health_checker: Callable = None):
        """Register a new component for health monitoring"""
        self.components[component_name] = ComponentHealth(
            component_name=component_name, status=HealthStatus.HEALTHY
        )

        logger.info(
            f"Registered component for health monitoring: {component_name}",
            extra={**self._log_context, "component_name": component_name},
        )

    def update_component_health(
        self,
        component_name: str,
        status: HealthStatus,
        metrics: Dict[str, Any] = None,
        error_message: str = None,
    ):
        """Update health status for a component"""
        if component_name not in self.components:
            self.register_component(component_name)

        component = self.components[component_name]
        old_status = component.status
        component.status = status
        component.error_message = error_message
        component.last_updated = datetime.now()

        # Add metrics if provided
        if metrics:
            for metric_name, metric_value in metrics.items():
                # Create threshold-based metric
                if isinstance(metric_value, (int, float)):
                    # Define default thresholds (can be customized per metric)
                    warning_threshold = self._get_warning_threshold(
                        metric_name, metric_value
                    )
                    critical_threshold = self._get_critical_threshold(
                        metric_name, metric_value
                    )

                    metric_status = self._determine_metric_status(
                        metric_value, warning_threshold, critical_threshold
                    )

                    health_metric = HealthMetric(
                        name=metric_name,
                        value=metric_value,
                        status=metric_status,
                        threshold_warning=warning_threshold,
                        threshold_critical=critical_threshold,
                        unit=self._get_metric_unit(metric_name),
                        description=self._get_metric_description(metric_name),
                    )

                    component.add_metric(health_metric)

                    # Store metric history
                    self.metrics_history[f"{component_name}.{metric_name}"].append(
                        {
                            "timestamp": datetime.now().isoformat(),
                            "value": metric_value,
                            "status": metric_status.value,
                        }
                    )

        # Update overall status
        self._update_overall_status()

        # Log status changes with intelligent frequency
        if old_status != status or status != HealthStatus.HEALTHY:
            if status == HealthStatus.HEALTHY:
                logger.info(
                    f"Component health updated: {component_name} -> {status.value}",
                    extra={
                        **self._log_context,
                        "component_name": component_name,
                        "old_status": old_status.value,
                        "new_status": status.value,
                        "error_message": error_message,
                        "metrics": metrics,
                    },
                )
            else:
                logger.warning(
                    f"Component health updated: {component_name} -> {status.value}",
                    extra={
                        **self._log_context,
                        "component_name": component_name,
                        "old_status": old_status.value,
                        "new_status": status.value,
                        "error_message": error_message,
                        "metrics": metrics,
                    },
                )

        # Check for alerts
        self._check_alerts(component_name, status, error_message)

    def add_performance_counter(self, counter_name: str, increment: int = 1):
        """Add to performance counter"""
        self.performance_counters[counter_name] += increment

    def record_timing(self, operation_name: str, duration: float):
        """Record timing data for an operation"""
        self.timing_data[operation_name].append(duration)

        # Keep only recent timings (last 1000)
        if len(self.timing_data[operation_name]) > 1000:
            self.timing_data[operation_name] = self.timing_data[operation_name][-1000:]

    def add_alert_handler(self, handler: Callable):
        """Add alert handler function"""
        self.alert_handlers.append(handler)

    def _update_overall_status(self):
        """Update overall service status based on components"""
        if not self.components:
            self.overall_status = HealthStatus.HEALTHY
            return

        # Determine worst status
        statuses = [comp.status for comp in self.components.values()]

        if HealthStatus.CRITICAL in statuses:
            self.overall_status = HealthStatus.CRITICAL
        elif HealthStatus.UNHEALTHY in statuses:
            self.overall_status = HealthStatus.UNHEALTHY
        elif HealthStatus.DEGRADED in statuses:
            self.overall_status = HealthStatus.DEGRADED
        else:
            self.overall_status = HealthStatus.HEALTHY

    def _check_alerts(
        self, component_name: str, status: HealthStatus, error_message: str = None
    ):
        """Check if alerts should be triggered"""
        # Only alert on unhealthy or critical status
        if status not in [HealthStatus.UNHEALTHY, HealthStatus.CRITICAL]:
            return

        # Check cooldown
        alert_key = f"{component_name}_{status.value}"
        now = datetime.now()

        if alert_key in self.alert_cooldown:
            if now - self.alert_cooldown[alert_key] < self.alert_cooldown_duration:
                return

        # Trigger alerts
        alert_data = {
            "component": component_name,
            "status": status.value,
            "timestamp": now.isoformat(),
            "error_message": error_message,
            "service": "mqtt_proxy",
        }

        for handler in self.alert_handlers:
            try:
                asyncio.create_task(handler(alert_data))
            except Exception as e:
                logger.error(
                    f"Error in alert handler: {e}",
                    extra={**self._log_context, "alert_data": alert_data},
                    exc_info=True,
                )

        # Set cooldown
        self.alert_cooldown[alert_key] = now

        logger.warning(
            f"Health alert triggered for {component_name}: {status.value}",
            extra={**self._log_context, "alert_data": alert_data},
        )

    def _get_warning_threshold(self, metric_name: str, value: float) -> float:
        """Get warning threshold for a metric"""
        # Default thresholds - can be customized per metric
        thresholds = {
            "cpu_usage": 80.0,
            "memory_usage": 85.0,
            "disk_usage": 90.0,
            "error_rate": 5.0,
            "response_time": 2.0,
            "connection_count": 1000,
            "queue_size": 1000,
            "failure_rate": 2.0,
        }

        return thresholds.get(metric_name, value * 1.5)

    def _get_critical_threshold(self, metric_name: str, value: float) -> float:
        """Get critical threshold for a metric"""
        # Default thresholds - can be customized per metric
        thresholds = {
            "cpu_usage": 95.0,
            "memory_usage": 95.0,
            "disk_usage": 95.0,
            "error_rate": 10.0,
            "response_time": 5.0,
            "connection_count": 2000,
            "queue_size": 2000,
            "failure_rate": 10.0,
        }

        return thresholds.get(metric_name, value * 2.0)

    def _determine_metric_status(
        self, value: float, warning: float, critical: float
    ) -> HealthStatus:
        """Determine metric status based on thresholds"""
        if value >= critical:
            return HealthStatus.CRITICAL
        elif value >= warning:
            return HealthStatus.UNHEALTHY
        elif value >= warning * 0.8:
            return HealthStatus.DEGRADED
        else:
            return HealthStatus.HEALTHY

    def _get_metric_unit(self, metric_name: str) -> str:
        """Get unit for a metric"""
        units = {
            "cpu_usage": "%",
            "memory_usage": "%",
            "disk_usage": "%",
            "error_rate": "%",
            "response_time": "ms",
            "connection_count": "connections",
            "queue_size": "items",
            "failure_rate": "%",
            "throughput": "msg/s",
        }

        return units.get(metric_name, "")

    def _get_metric_description(self, metric_name: str) -> str:
        """Get description for a metric"""
        descriptions = {
            "cpu_usage": "CPU utilization percentage",
            "memory_usage": "Memory utilization percentage",
            "disk_usage": "Disk utilization percentage",
            "error_rate": "Error rate percentage",
            "response_time": "Average response time",
            "connection_count": "Number of active connections",
            "queue_size": "Number of items in queue",
            "failure_rate": "Failure rate percentage",
            "throughput": "Messages processed per second",
        }

        return descriptions.get(metric_name, "")

    async def _monitor_loop(self):
        """Background monitoring loop"""
        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(self.config.health_check_interval)

                # Record health snapshot
                health_snapshot = {
                    "timestamp": datetime.now().isoformat(),
                    "overall_status": self.overall_status.value,
                    "components": {
                        name: comp.status.value
                        for name, comp in self.components.items()
                    },
                }

                self.health_history.append(health_snapshot)

                # Log health status periodically
                if len(self.health_history) % 10 == 0:  # Every 10 checks
                    logger.info(
                        f"Health monitor check: {self.overall_status.value}",
                        extra={
                            **self._log_context,
                            "overall_status": self.overall_status.value,
                            "components": len(self.components),
                            "uptime": self.get_uptime(),
                        },
                    )

        except asyncio.CancelledError:
            logger.info("Health monitor loop cancelled", extra=self._log_context)
        except Exception as e:
            logger.error(
                f"Unexpected error in health monitor loop: {e}",
                extra=self._log_context,
                exc_info=True,
            )

    async def _metrics_loop(self):
        """Background metrics collection loop"""
        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(60)  # Run every minute

                # Collect system metrics
                system_metrics = self._collect_system_metrics()

                # Update system component health
                self.update_component_health(
                    "system", HealthStatus.HEALTHY, system_metrics
                )

        except asyncio.CancelledError:
            logger.info("Metrics collection loop cancelled", extra=self._log_context)
        except Exception as e:
            logger.error(
                f"Unexpected error in metrics collection loop: {e}",
                extra=self._log_context,
                exc_info=True,
            )

    async def _cleanup_loop(self):
        """Background cleanup loop"""
        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(300)  # Run every 5 minutes

                # Clean up old timing data
                for operation_name in self.timing_data:
                    if len(self.timing_data[operation_name]) > 1000:
                        self.timing_data[operation_name] = self.timing_data[
                            operation_name
                        ][-1000:]

                # Clean up old alert cooldowns
                cutoff_time = datetime.now() - self.alert_cooldown_duration * 2
                self.alert_cooldown = {
                    key: value
                    for key, value in self.alert_cooldown.items()
                    if value > cutoff_time
                }

        except asyncio.CancelledError:
            logger.info("Cleanup loop cancelled", extra=self._log_context)
        except Exception as e:
            logger.error(
                f"Unexpected error in cleanup loop: {e}",
                extra=self._log_context,
                exc_info=True,
            )

    def _collect_system_metrics(self) -> Dict[str, Any]:
        """Collect system-level metrics"""
        import psutil

        try:
            return {
                "cpu_usage": psutil.cpu_percent(interval=1),
                "memory_usage": psutil.virtual_memory().percent,
                "disk_usage": psutil.disk_usage("/").percent,
                "load_average": (
                    psutil.getloadavg()[0] if hasattr(psutil, "getloadavg") else 0
                ),
                "open_files": (
                    len(psutil.Process().open_files())
                    if hasattr(psutil.Process(), "open_files")
                    else 0
                ),
            }
        except Exception as e:
            logger.error(
                f"Error collecting system metrics: {e}", extra=self._log_context
            )
            return {}

    def get_uptime(self) -> Dict[str, Any]:
        """Get service uptime"""
        uptime_delta = datetime.now() - self.start_time
        return {
            "seconds": uptime_delta.total_seconds(),
            "human_readable": str(uptime_delta).split(".")[0],  # Remove microseconds
        }

    def get_health_status(self) -> Dict[str, Any]:
        """Get overall health status"""
        return {
            "status": self.overall_status.value,
            "timestamp": datetime.now().isoformat(),
            "uptime": self.get_uptime(),
            "components": {
                name: {
                    "status": comp.status.value,
                    "last_updated": comp.last_updated.isoformat(),
                    "error_message": comp.error_message,
                }
                for name, comp in self.components.items()
            },
            "summary": {
                "total_components": len(self.components),
                "healthy_components": len(
                    [
                        c
                        for c in self.components.values()
                        if c.status == HealthStatus.HEALTHY
                    ]
                ),
                "degraded_components": len(
                    [
                        c
                        for c in self.components.values()
                        if c.status == HealthStatus.DEGRADED
                    ]
                ),
                "unhealthy_components": len(
                    [
                        c
                        for c in self.components.values()
                        if c.status == HealthStatus.UNHEALTHY
                    ]
                ),
                "critical_components": len(
                    [
                        c
                        for c in self.components.values()
                        if c.status == HealthStatus.CRITICAL
                    ]
                ),
            },
        }

    def get_detailed_metrics(self) -> Dict[str, Any]:
        """Get detailed metrics"""
        timing_stats = {}
        for operation, timings in self.timing_data.items():
            if timings:
                timing_stats[operation] = {
                    "count": len(timings),
                    "average": sum(timings) / len(timings),
                    "min": min(timings),
                    "max": max(timings),
                    "recent_average": (
                        sum(timings[-10:]) / len(timings[-10:])
                        if len(timings) >= 10
                        else sum(timings) / len(timings)
                    ),
                }

        return {
            "performance_counters": dict(self.performance_counters),
            "timing_statistics": timing_stats,
            "metrics_history_size": {
                name: len(history) for name, history in self.metrics_history.items()
            },
        }

    def get_component_health(self) -> Dict[str, Any]:
        """Get detailed component health"""
        component_details = {}

        for name, comp in self.components.items():
            component_details[name] = {
                "status": comp.status.value,
                "last_updated": comp.last_updated.isoformat(),
                "error_message": comp.error_message,
                "metrics": {
                    metric_name: {
                        "value": metric.value,
                        "status": metric.status.value,
                        "threshold_warning": metric.threshold_warning,
                        "threshold_critical": metric.threshold_critical,
                        "unit": metric.unit,
                        "description": metric.description,
                        "timestamp": metric.timestamp.isoformat(),
                    }
                    for metric_name, metric in comp.metrics.items()
                },
            }

        return component_details

    def get_health_history(self) -> Dict[str, Any]:
        """Get health history"""
        return {
            "history": list(self.health_history),
            "history_size": len(self.health_history),
            "oldest_entry": (
                self.health_history[0]["timestamp"] if self.health_history else None
            ),
            "newest_entry": (
                self.health_history[-1]["timestamp"] if self.health_history else None
            ),
        }
