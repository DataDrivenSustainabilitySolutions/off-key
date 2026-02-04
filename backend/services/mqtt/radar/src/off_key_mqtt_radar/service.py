"""
Main RADAR Service Orchestrator

Coordinates MQTT subscription, anomaly detection, and database persistence
with comprehensive monitoring and health checks.

Refactored to use extracted components:
- CheckpointManager: Handles checkpoint persistence
- MessageProcessor: Handles MQTT message processing
- HealthMonitor: Handles health checks and metrics
- TopicParser: Handles topic parsing utilities
"""

import asyncio
import os
import signal
import time
from datetime import datetime
from typing import Optional

from off_key_core.config.logs import logger

from .config import AnomalyDetectionConfig, get_radar_config
from .detector import (
    AnomalyDetectionService,
    ResilientAnomalyDetector,
    MemoryManager,
    SecurityValidator,
)
from .mqtt_client import RadarMQTTClient
from .database import DatabaseWriter, ensure_tables_exist
from .models import MQTTMessage, HealthStatus as RadarHealthStatus
from .config_watcher import ConfigWatcher, ConfigReloader
from .state_cache import SensorStateCache
from .checkpoint_manager import CheckpointManager
from .message_processor import MessageProcessor
from .health_monitor import HealthMonitor
from .topic_parser import TopicParser


class RadarService:
    """
    Main RADAR service orchestrator

    Coordinates:
    - MQTT message subscription and processing
    - Anomaly detection pipeline
    - Database persistence
    - Health monitoring and alerts
    - Resource management
    """

    def __init__(self, config_file_path: Optional[str] = None):
        self.config = get_radar_config()
        self.config_file_path = config_file_path or os.getenv("RADAR_CONFIG_FILE")

        # Core components
        self.mqtt_client: Optional[RadarMQTTClient] = None
        self.detector: Optional[ResilientAnomalyDetector] = None
        self.database_writer: Optional[DatabaseWriter] = None

        # Supporting components
        self.memory_manager = MemoryManager(
            max_memory_mb=self.config.memory_limit_mb, cleanup_threshold=0.8
        )
        self.security_validator = SecurityValidator(
            max_feature_count=self.config.max_feature_count,
            max_string_length=self.config.max_string_length,
        )

        # Extracted components
        self.checkpoint_manager = CheckpointManager()
        self.health_monitor = HealthMonitor(
            health_check_interval=self.config.health_check_interval
        )
        self.message_processor: Optional[MessageProcessor] = None

        # Service state
        self.is_running = False
        self.start_time: Optional[datetime] = None
        self.shutdown_event = asyncio.Event()

        # Configuration watching and reloading
        self.config_watcher: Optional[ConfigWatcher] = None
        self.config_reloader: Optional[ConfigReloader] = None

        # Logging context
        self._log_context = {"service": "radar", "component": "main"}

        # Sensor alignment (wait_for_all with latest values)
        self.required_sensors = TopicParser.derive_required_sensors(
            self.config.subscription_topics
        )
        self.state_cache = (
            SensorStateCache(self.required_sensors) if self.required_sensors else None
        )

        logger.info("Initialized RADAR service orchestrator")

    async def start(self):
        """Start the RADAR service"""
        if self.is_running:
            logger.warning("RADAR service already running")
            return

        logger.info("Starting RADAR service", extra=self._log_context)
        self.start_time = datetime.now()

        try:
            # Initialize anomaly detection
            await self._setup_anomaly_detection()

            # Initialize message processor
            self.message_processor = MessageProcessor(
                detector=self.detector,
                security_validator=self.security_validator,
                memory_manager=self.memory_manager,
                state_cache=self.state_cache,
                required_sensors=self.required_sensors,
            )

            # Initialize database writer only when enabled
            if self.config.db_write_enabled:
                await ensure_tables_exist()
                await self._setup_database_writer()
            else:
                logger.info(
                    "Database writing disabled by configuration; skipping DB setup",
                    extra=self._log_context,
                )

            # Initialize MQTT client
            await self._setup_mqtt_client()

            # Start health monitoring with component references
            self.health_monitor.set_components(
                mqtt_client=self.mqtt_client,
                database_writer=self.database_writer,
                detector=self.detector,
                memory_manager=self.memory_manager,
                message_processor=self.message_processor,
            )
            await self.health_monitor.start(self.shutdown_event)

            # Setup configuration watching
            await self._setup_config_watcher()

            self.is_running = True

            logger.info(
                "RADAR service started successfully",
                extra={
                    **self._log_context,
                    "subscribed_topics": self.config.subscription_topics,
                    "model_type": self.config.model_type,
                    "db_enabled": self.config.db_write_enabled,
                },
            )

        except Exception as e:
            logger.error(f"Failed to start RADAR service: {e}", extra=self._log_context)
            await self.stop()
            raise

    async def stop(self):
        """Stop the RADAR service"""
        if not self.is_running:
            logger.info("RADAR service already stopped")
            return

        logger.info("Stopping RADAR service", extra=self._log_context)

        # Signal shutdown
        self.shutdown_event.set()
        self.is_running = False

        # Stop components in reverse order
        components = [
            ("config_watcher", self.config_watcher),
            ("health_monitor", self.health_monitor),
            ("mqtt_client", self.mqtt_client),
            ("database_writer", self.database_writer),
        ]

        for component_name, component in components:
            if component:
                try:
                    if hasattr(component, "stop"):
                        await component.stop()
                    elif hasattr(component, "cancel"):
                        component.cancel()
                        try:
                            await component
                        except asyncio.CancelledError:
                            pass

                    logger.info(f"Stopped {component_name}")
                except Exception as e:
                    logger.error(f"Error stopping {component_name}: {e}")

        # Cleanup checkpoint lock file using extracted manager
        self.checkpoint_manager.cleanup_lock()

        logger.info("RADAR service stopped")

    async def _setup_anomaly_detection(self):
        """Initialize anomaly detection components.

        Attempts to restore from a checkpoint if one exists for this service.
        Otherwise creates a fresh instance.
        """
        logger.info("Setting up anomaly detection")

        # Create anomaly detection config
        anomaly_config = AnomalyDetectionConfig(
            model_type=getattr(self.config, "model_type", "isolation_forest"),
            model_params=getattr(self.config, "model_params", {}),
            preprocessing_steps=getattr(self.config, "preprocessing_steps", []),
            thresholds=getattr(
                self.config, "thresholds", {"medium": 0.6, "high": 0.8, "critical": 0.9}
            ),
            batch_size=getattr(self.config, "batch_size", 100),
            batch_timeout=getattr(self.config, "batch_timeout", 1.0),
            memory_limit_mb=getattr(self.config, "memory_limit_mb", 1000),
            checkpoint_interval=getattr(self.config, "checkpoint_interval", 10000),
        )

        # Try to restore from checkpoint using extracted manager
        checkpoint_path = self.checkpoint_manager.find_latest_checkpoint()
        if checkpoint_path:
            try:
                logger.info(
                    f"Found checkpoint, attempting restore: {checkpoint_path}",
                    extra=self._log_context,
                )
                primary_service = AnomalyDetectionService.from_checkpoint(
                    checkpoint_path, anomaly_config
                )
                logger.info(
                    "Successfully restored from checkpoint",
                    extra={
                        **self._log_context,
                        "checkpoint_path": checkpoint_path,
                        "processed_count": primary_service.processed_count,
                    },
                )
            except Exception as e:
                logger.warning(
                    f"Failed to load checkpoint, starting fresh: {e}",
                    extra=self._log_context,
                )
                primary_service = AnomalyDetectionService(anomaly_config)
        else:
            logger.info("No checkpoint found, starting fresh", extra=self._log_context)
            primary_service = AnomalyDetectionService(anomaly_config)

        # Create resilient detector (with fallback)
        self.detector = ResilientAnomalyDetector(primary_service)

        logger.info(
            f"Anomaly detection setup complete with model: {anomaly_config.model_type}"
        )

        if self.required_sensors and self.state_cache:
            logger.info(
                "Sensor alignment enabled (wait_for_all)",
                extra={**self._log_context, "required_sensors": self.required_sensors},
            )

    async def _setup_database_writer(self):
        """Initialize database writer"""
        if not self.config.db_write_enabled:
            logger.info("Database writing disabled; not creating writer")
            return

        logger.info("Setting up database writer")

        self.database_writer = DatabaseWriter(self.config)
        await self.database_writer.start()

        logger.info("Database writer setup complete")

    async def _setup_mqtt_client(self):
        """Initialize MQTT client and message handling"""
        logger.info("Setting up MQTT client")

        self.mqtt_client = RadarMQTTClient(self.config)
        self.mqtt_client.set_message_handler(self._handle_mqtt_message)
        await self.mqtt_client.start()

        logger.info("MQTT client setup complete")

    async def _setup_config_watcher(self):
        """Setup configuration file watching for hot reload"""
        try:
            # Check if we have a config file to watch
            config_file_path = self.config_file_path

            if not config_file_path:
                logger.info("No configuration file specified for watching")
                return

            logger.info(
                f"Setting up configuration file watcher for: {config_file_path}"
            )

            # Create config reloader
            self.config_reloader = ConfigReloader(self)

            # Create config watcher
            self.config_watcher = ConfigWatcher(
                config_file_path, self.config_reloader.reload_config
            )

            # Start watching
            await self.config_watcher.start()

            logger.info("Configuration file watcher setup complete")

        except Exception as e:
            logger.error(f"Failed to setup configuration watcher: {e}")
            # Don't fail the service startup if config watching fails

    async def _handle_mqtt_message(self, message: MQTTMessage):
        """Handle incoming MQTT message using extracted MessageProcessor."""
        start_time = time.time()

        try:
            # Delegate to message processor
            result = await self.message_processor.process_message(message)

            if result:
                # Record processing time in health monitor
                self.health_monitor.record_processing_time(time.time() - start_time)

                # Write results to database if needed
                if result.is_anomaly or getattr(
                    self.config, "write_all_results", False
                ):
                    if self.database_writer:
                        await self.database_writer.write_anomaly(result)

        except Exception as e:
            logger.error(
                f"Error processing message from {message.topic}: {e}", exc_info=True
            )

    async def _health_monitor(self):
        """Periodic health monitoring and metrics collection"""
        logger.info("Started health monitor")

        try:
            while not self.shutdown_event.is_set():
                try:
                    # Wait for health check interval
                    await asyncio.wait_for(
                        self.shutdown_event.wait(),
                        timeout=self.config.health_check_interval,
                    )
                    break  # Shutdown event was set
                except asyncio.TimeoutError:
                    # Perform health check
                    await self._perform_health_check()

        except asyncio.CancelledError:
            logger.info("Health monitor cancelled")
        except Exception as e:
            logger.error(f"Health monitor error: {e}")

        logger.info("Health monitor stopped")

    async def _perform_health_check(self):
        """Perform comprehensive health check"""
        try:
            health_status = self.get_health_status()

            # Log health status
            if health_status.status in ["degraded", "failed"]:
                logger.warning(
                    f"Service health: {health_status.status}", extra=self._log_context
                )
                for alert in health_status.active_alerts:
                    logger.warning(f"Active alert: {alert}", extra=self._log_context)
            else:
                logger.debug(
                    f"Service health: {health_status.status}", extra=self._log_context
                )

            # Write metrics to database
            if self.database_writer and health_status.status != "failed":
                metrics = {
                    "total_messages_processed": self.message_count,
                    "total_anomalies_detected": self.anomaly_count,
                    "anomaly_rate": self.anomaly_count / max(self.message_count, 1),
                    "avg_processing_time_ms": sum(self.processing_times)
                    / max(len(self.processing_times), 1)
                    * 1000,
                    "throughput_per_second": self._calculate_throughput(),
                    "memory_usage_mb": self.memory_manager.get_memory_usage(),
                    "error_count": self.error_count,
                    "error_rate": self.error_count / max(self.message_count, 1),
                    "service_status": health_status.status,
                    "active_alerts": health_status.active_alerts,
                }

                await self.database_writer.write_service_metrics(metrics)

            self.last_health_check = time.time()

        except Exception as e:
            logger.error(f"Health check failed: {e}")

    def _calculate_throughput(self) -> float:
        """Calculate current message processing throughput"""
        if not self.start_time:
            return 0.0

        uptime = (datetime.now() - self.start_time).total_seconds()
        if uptime <= 0:
            return 0.0

        return self.message_count / uptime

    async def run(self):
        """Run the RADAR service with signal handling"""

        # Set up signal handlers
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating graceful shutdown")
            asyncio.create_task(self.stop())

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            # Start the service
            await self.start()

            # Keep running until shutdown
            await self.shutdown_event.wait()

        except Exception as e:
            logger.error(f"Unexpected error in RADAR service: {e}", exc_info=True)
        finally:
            # Ensure cleanup
            await self.stop()

    def get_health_status(self) -> RadarHealthStatus:
        """Get comprehensive health status using HealthMonitor."""
        return self.health_monitor.get_health_status()


# Global service instance
_radar_service: Optional[RadarService] = None


def get_radar_service(config_file_path: Optional[str] = None) -> RadarService:
    """Get the global RADAR service instance."""
    global _radar_service
    if _radar_service is None:
        _radar_service = RadarService(config_file_path=config_file_path)
    elif config_file_path:
        _radar_service.config_file_path = config_file_path
    return _radar_service
