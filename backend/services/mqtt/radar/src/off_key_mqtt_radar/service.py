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
import signal
import time
from contextlib import suppress
from datetime import datetime

from off_key_core.config.logs import logger

from .adaptive_detector import AdaptiveStreamDetectionService
from .admission import require_monitor_admission
from .checkpoint_manager import CheckpointManager
from .config.config import AnomalyDetectionConfig, get_radar_settings
from .config.runtime import get_radar_checkpoint_settings
from .database import (
    CheckpointOwnershipLost,
    DatabaseWriter,
    ensure_radar_metrics_tables,
)
from .detector import StaticConformalDetectionService
from .detector_runtime import DetectorRuntime
from .execution_errors import FatalExecutionError
from .feature_validation import TelemetryFeatureValidator
from .health_monitor import HealthMonitor
from .memory import MemoryManager
from .message_processor import MessageProcessor
from .models import HealthStatus as RadarHealthStatus
from .models import MQTTMessage
from .mqtt_client import RadarMQTTClient
from .resilience import ResilientAnomalyDetector
from .runtime_checkpoint import (
    CoverageCheckpoint,
    ProcessorCheckpoint,
    RuntimeCheckpoint,
    RuntimeCheckpointCodec,
)
from .state_cache import SensorStateCache
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

    def __init__(self):
        self.config = get_radar_settings().config

        # Core components
        self.mqtt_client: RadarMQTTClient | None = None
        self.detector: ResilientAnomalyDetector | None = None
        self.database_writer: DatabaseWriter | None = None

        # Supporting components
        self.memory_manager = MemoryManager(
            max_memory_mb=self.config.memory_limit_mb, cleanup_threshold=0.8
        )
        self.feature_validator = TelemetryFeatureValidator(
            max_feature_count=self.config.max_feature_count,
            max_string_length=self.config.max_string_length,
        )

        # Extracted components
        self.checkpoint_manager = CheckpointManager()
        self.health_monitor = HealthMonitor(
            health_check_interval=self.config.health_check_interval,
            sensor_freshness_seconds=self.config.sensor_freshness_seconds,
        )
        self.message_processor: MessageProcessor | None = None

        # Service state
        self.is_running = False
        self.start_time: datetime | None = None
        self.shutdown_event = asyncio.Event()
        self._processing_lock = asyncio.Lock()
        self._detector_runtime: DetectorRuntime | None = None
        self._checkpoint_task: asyncio.Task | None = None
        self._checkpoint_codec: RuntimeCheckpointCodec | None = None
        self._checkpoint_ready = False
        self._checkpoint_phase: str | None = None
        self._checkpoint_saved_monotonic = 0.0
        self._checkpoint_received_count = 0
        self._checkpoint_gap: tuple | None = None
        self._restored_processor: ProcessorCheckpoint | None = None
        self._restored_coverage: dict = {}
        self._restored_observation_watermarks: dict[str, dict[str, float]] = {}
        self._checkpoint_restored = False
        self._fatal_error: Exception | None = None
        self.recovery_status: dict = {"storage": "file", "restored": False}

        # Logging context
        self._log_context = {"service": "radar", "component": "main"}

        # Sensor alignment (wait_for_all with latest values)
        self.required_sensors = TopicParser.derive_required_sensors(
            self.config.subscription_topics,
            sensor_key_strategy=self.config.sensor_key_strategy,
        )
        self.state_cache = (
            SensorStateCache(
                self.required_sensors,
                max_sensor_age_seconds=self.config.sensor_freshness_seconds,
                observation_max_age_seconds=self.config.observation_max_age_seconds,
                observation_future_tolerance_seconds=self.config.observation_future_tolerance_seconds,
                alignment_max_skew_seconds=self.config.alignment_max_skew_seconds,
            )
            if self.required_sensors
            else None
        )

        logger.info("Initialized RADAR service orchestrator")

    async def start(self):
        """Start the RADAR service"""
        if self.is_running:
            logger.debug("event=radar.service_already_running")
            return

        logger.info("Starting RADAR service", extra=self._log_context)
        self.start_time = datetime.now()
        self.shutdown_event.clear()

        try:
            await require_monitor_admission()
            runtime = get_radar_checkpoint_settings()
            if runtime.RADAR_CHECKPOINT_STORAGE == "database":
                if not self.config.db_write_enabled:
                    raise ValueError("Managed checkpoints require database writes")
                self._checkpoint_codec = RuntimeCheckpointCodec(
                    runtime.SERVICE_ID,
                    self.config,
                    runtime.durable_checkpoint_secret_bytes,
                )

            # Durable recovery must complete before MQTT receives live input.
            if self.config.db_write_enabled:
                await ensure_radar_metrics_tables()
                await self._setup_database_writer()

            # Initialize anomaly detection
            await self._setup_anomaly_detection()
            self._detector_runtime = DetectorRuntime(self.detector)
            await self._detector_runtime.refresh()

            # Initialize message processor
            self.message_processor = MessageProcessor(
                detector=self.detector,
                feature_validator=self.feature_validator,
                memory_manager=self.memory_manager,
                state_cache=self.state_cache,
                required_sensors=self.required_sensors,
                sensor_key_strategy=self.config.sensor_key_strategy,
                observation_max_age_seconds=self.config.observation_max_age_seconds,
                sensor_freshness_seconds=self.config.sensor_freshness_seconds,
                observation_future_tolerance_seconds=self.config.observation_future_tolerance_seconds,
            )
            if self._restored_processor is not None:
                for name, value in self._restored_processor.model_dump().items():
                    setattr(self.message_processor, name, value)
            self.message_processor.restore_observation_watermarks(
                self._restored_observation_watermarks
            )

            await self._checkpoint_if_due(force=True)

            # Initialize MQTT client
            await self._setup_mqtt_client()
            self._checkpoint_task = asyncio.create_task(self._checkpoint_loop())

            # Start health monitoring with component references
            self.health_monitor.set_components(
                mqtt_client=self.mqtt_client,
                database_writer=self.database_writer,
                detector=self._detector_runtime,
                memory_manager=self.memory_manager,
                message_processor=self.message_processor,
                recovery_status=lambda: self.recovery_status,
            )
            await self.health_monitor.start(self.shutdown_event)

            self.is_running = True
            if self.database_writer:
                await self.database_writer.write_service_metrics(
                    self.health_monitor.build_metrics_snapshot()
                )

            logger.info(
                "RADAR service started successfully",
                extra={
                    **self._log_context,
                    "subscribed_topics": self.config.subscription_topics,
                    "model_type": self.config.monitoring.model_type,
                    "db_enabled": self.config.db_write_enabled,
                },
            )

        except BaseException as e:
            logger.error(
                "event=radar.start_failed error=%s",
                str(e),
                extra=self._log_context,
                exc_info=True,
            )
            await self.stop()
            raise

    async def stop(self):
        """Stop the RADAR service"""
        has_started_components = any(
            [
                self.mqtt_client,
                self.detector,
                self.database_writer,
                self.message_processor,
            ]
        )
        if (
            not self.is_running
            and self.shutdown_event.is_set()
            and not has_started_components
        ):
            logger.debug("event=radar.service_already_stopped")
            return

        logger.info("Stopping RADAR service", extra=self._log_context)

        # Signal shutdown
        self.shutdown_event.set()
        self.is_running = False
        final_checkpoint_error = await self._stop_ingestion_and_checkpoint()

        # Stop components in reverse order
        components = [
            ("detector_runtime", getattr(self, "_detector_runtime", None)),
            ("detector", self.detector),
            ("database_writer", self.database_writer),
        ]

        for component_name, component in components:
            if component:
                try:
                    if hasattr(component, "stop"):
                        await component.stop()
                    elif hasattr(component, "cancel"):
                        component.cancel()
                        with suppress(asyncio.CancelledError):
                            await component

                    logger.debug(
                        "event=radar.component_stopped component=%s", component_name
                    )
                except Exception as e:
                    logger.error(
                        "event=radar.component_stop_failed component=%s error=%s",
                        component_name,
                        str(e),
                        exc_info=True,
                    )

        self.mqtt_client = None
        self.detector = None
        self.database_writer = None
        self.message_processor = None
        self._detector_runtime = None

        # Cleanup checkpoint lock file using extracted manager
        self.checkpoint_manager.cleanup_lock()

        logger.info("RADAR service stopped")
        if final_checkpoint_error is not None:
            raise RuntimeError(
                "RADAR final checkpoint failed"
            ) from final_checkpoint_error

    async def _stop_ingestion_and_checkpoint(self) -> Exception | None:
        checkpoint_task = getattr(self, "_checkpoint_task", None)
        if checkpoint_task:
            checkpoint_task.cancel()
            with suppress(asyncio.CancelledError):
                await checkpoint_task
            self._checkpoint_task = None
        # Finish the in-flight handler before freezing the final detector state.
        for component in (self.health_monitor, self.mqtt_client):
            if component is not None:
                try:
                    await component.stop()
                except Exception:
                    logger.exception("event=radar.component_stop_failed")
        if getattr(self, "_checkpoint_ready", False) and not isinstance(
            self._fatal_error, FatalExecutionError
        ):
            try:
                async with self._processing_lock:
                    await self._checkpoint_if_due(force=True)
            except Exception as error:
                logger.exception("event=radar.final_checkpoint_failed")
                return error
        return None

    async def _setup_anomaly_detection(self):
        """Initialize anomaly detection components.

        Attempts to restore from a checkpoint if one exists for this service.
        Otherwise creates a fresh instance.
        """
        logger.info("Setting up anomaly detection")

        anomaly_config = AnomalyDetectionConfig.model_validate(
            self.config.model_dump(include=set(AnomalyDetectionConfig.model_fields))
        )
        service_cls = self._detector_service_class(anomaly_config)
        primary_service = None
        codec = getattr(self, "_checkpoint_codec", None)
        if codec is not None:
            record = await self.database_writer.load_checkpoint(codec.service_id)
            self.recovery_status = {
                "storage": "database",
                "restored": record is not None,
            }
            if record is not None:
                snapshot = codec.decode(record)
                if record["processed_count"] > 0 and not any(
                    snapshot.observation_watermarks.values()
                ):
                    raise ValueError(
                        "Managed checkpoint is missing observation replay history"
                    )
                primary_service = service_cls.from_checkpoint_data(
                    snapshot.detector,
                    anomaly_config,
                    automatic_checkpoints=False,
                )
                self._restored_processor = snapshot.processor
                self._restored_coverage = snapshot.coverage.data
                self._restored_observation_watermarks = snapshot.observation_watermarks
                self._checkpoint_restored = True
                self.recovery_status.update(
                    restored_processed_count=record["processed_count"],
                    restored_saved_at=record["saved_at"].isoformat(),
                    input_recovery="live_only_with_possible_gap",
                )
            else:
                primary_service = service_cls(
                    anomaly_config, automatic_checkpoints=False
                )

        for checkpoint_path in (
            [] if codec is not None else self.checkpoint_manager.candidate_paths()
        ):
            if not self.checkpoint_manager.claim(checkpoint_path):
                continue
            try:
                logger.info(
                    f"Found checkpoint, attempting restore: {checkpoint_path}",
                    extra=self._log_context,
                )
                primary_service = service_cls.from_checkpoint(
                    checkpoint_path, anomaly_config
                )
                self._checkpoint_restored = True
                self.recovery_status = {
                    "storage": "file",
                    "restored": True,
                    "restored_processed_count": primary_service.processed_count,
                    "input_recovery": "live_only_with_possible_gap",
                }
                logger.info(
                    "Successfully restored from checkpoint",
                    extra={
                        **self._log_context,
                        "checkpoint_path": checkpoint_path,
                        "processed_count": primary_service.processed_count,
                    },
                )
                break
            except Exception as e:
                logger.warning(
                    "event=radar.checkpoint_restore_failed error=%s",
                    str(e),
                    extra=self._log_context,
                    exc_info=True,
                )
                self.checkpoint_manager.cleanup_lock()

        if primary_service is None:
            logger.info("No checkpoint found, starting fresh", extra=self._log_context)
            primary_service = service_cls(anomaly_config)

        # Create resilient detector (with fallback)
        self.detector = ResilientAnomalyDetector(primary_service)
        if codec is not None:
            self._checkpoint_ready = True

        logger.info(
            "Anomaly detection setup complete with model: "
            f"{anomaly_config.monitoring.model_type} "
            f"strategy={anomaly_config.monitoring.strategy}"
        )

        if self.required_sensors and self.state_cache:
            logger.info(
                "Sensor alignment enabled (wait_for_all)",
                extra={
                    **self._log_context,
                    "required_sensors": self.required_sensors,
                    "sensor_freshness_seconds": self.config.sensor_freshness_seconds,
                },
            )
        else:
            logger.info(
                (
                    "Sensor alignment disabled; processing incoming sensor "
                    "streams independently"
                ),
                extra={
                    **self._log_context,
                    "subscription_topics": self.config.subscription_topics,
                    "sensor_key_strategy": self.config.sensor_key_strategy,
                },
            )

    async def _setup_database_writer(self):
        """Initialize database writer"""
        if not self.config.db_write_enabled:
            logger.info("Database writing disabled; not creating writer")
            return

        logger.info("Setting up database writer")

        self.database_writer = DatabaseWriter(
            self.config, managed_checkpoints=self._checkpoint_codec is not None
        )
        await self.database_writer.start()

        logger.info("Database writer setup complete")

    async def _setup_mqtt_client(self):
        """Initialize MQTT client and message handling"""
        logger.info("Setting up MQTT client")

        self.mqtt_client = RadarMQTTClient(self.config)
        coverage = getattr(self.mqtt_client, "coverage", None)
        if coverage is not None:
            if self._restored_coverage:
                coverage.restore(self._restored_coverage)
            if self._checkpoint_restored:
                coverage.record_possible_gap("worker_restart")
            self.message_processor.coverage = coverage
        self.mqtt_client.set_message_handler(self._handle_mqtt_message)
        await self.mqtt_client.start()

        logger.info("MQTT client setup complete")

    async def _handle_mqtt_message(self, message: MQTTMessage):
        """Handle incoming MQTT message using extracted MessageProcessor."""
        # Shutdown must not cancel between model advancement and evidence enqueue.
        operation = asyncio.create_task(self._process_one_message(message))
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError:
            await operation
            raise

    async def _process_one_message(self, message: MQTTMessage):
        async with self._processing_lock:
            if self._fatal_error is not None:
                return
            await self._process_locked_message(message)

    async def _process_locked_message(self, message: MQTTMessage):
        start_time = time.time()

        try:
            if self.database_writer is not None:
                self.database_writer.raise_if_fenced()
            # Delegate to message processor
            runtime = getattr(self, "_detector_runtime", None)
            result = (
                await runtime.call(self.message_processor.process_message_sync, message)
                if runtime is not None
                else await self.message_processor.process_message(message)
            )

            if result:
                # Record processing time in health monitor
                self.health_monitor.record_processing_time(time.time() - start_time)

                # Write results to database if needed
                if self.database_writer and result.should_persist:
                    await self.database_writer.write_result(result)
            await self._checkpoint_if_due()

        except FatalExecutionError as error:
            await self._fail_execution(error)
        except Exception as e:
            logger.error(
                f"Error processing message from {message.topic}: {e}", exc_info=True
            )
            if self._checkpoint_codec is not None:
                self._fatal_error = e
                self.shutdown_event.set()

    async def _fail_execution(self, error: FatalExecutionError) -> None:
        """Quarantine uncertain state before any asynchronous cleanup or I/O."""
        self._fatal_error = error
        self._checkpoint_ready = False
        self.recovery_status["execution_failed"] = True
        logger.error("event=radar.execution_state_uncertain error=%s", error)
        if (
            self.database_writer is not None
            and self.database_writer.managed_checkpoints
        ):
            diagnostics = None
            coverage = None
            try:
                runtime = getattr(self, "_detector_runtime", None)
                if runtime is not None:
                    diagnostics = (
                        runtime.get_health_info()
                        .get("primary_service_stats", {})
                        .get("pipeline_state")
                    )
                tracker = getattr(self.mqtt_client, "coverage", None)
                if tracker is not None:
                    coverage = tracker.snapshot().model_dump(mode="json")
            except Exception:
                logger.exception("event=radar.final_failure_diagnostics_failed")
            await self._persist_execution_failure(error, diagnostics, coverage)
        self.shutdown_event.set()

    async def _persist_execution_failure(self, error, diagnostics, coverage):
        # A transient outage must not turn a known fatal execution into an
        # ordinary Swarm restart before its durable admission fence is stored.
        # Explicit operator shutdown can still terminate this quarantined worker.
        settings = get_radar_checkpoint_settings()
        while not self.shutdown_event.is_set():
            try:
                async with asyncio.timeout(settings.RADAR_CHECKPOINT_TIMEOUT_SECONDS):
                    await self.database_writer.fail_pipeline_run(
                        str(error), diagnostics=diagnostics, coverage=coverage
                    )
                return
            except CheckpointOwnershipLost:
                return  # A successor already owns the signed-state generation.
            except Exception:
                logger.exception("event=radar.execution_failure_persistence_retry")
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    self.shutdown_event.wait(),
                    settings.RADAR_FATAL_PERSIST_RETRY_SECONDS,
                )

    @staticmethod
    def _detector_service_class(config):
        if config.pipeline is not None:
            from .pipelines.adaptive import AdaptivePipelineDetectionService
            from .pipelines.static import StaticPipelineDetectionService

            return (
                AdaptivePipelineDetectionService
                if config.monitoring.strategy == "adaptive_stream"
                else StaticPipelineDetectionService
            )
        return (
            AdaptiveStreamDetectionService
            if config.monitoring.strategy == "adaptive_stream"
            else StaticConformalDetectionService
        )

    async def _checkpoint_if_due(self, *, force: bool = False) -> None:
        codec = getattr(self, "_checkpoint_codec", None)
        if (
            codec is None
            or not self._checkpoint_ready
            or isinstance(self._fatal_error, FatalExecutionError)
        ):
            return
        self.database_writer.raise_if_fenced()
        runtime = getattr(self, "_detector_runtime", None)
        captured = (
            await runtime.call(self._freeze_checkpoint, force)
            if runtime is not None
            else self._freeze_checkpoint(force)
        )
        if captured is None:
            return
        checkpoint, processor, phase, gap = captured
        async with asyncio.timeout(
            get_radar_checkpoint_settings().RADAR_CHECKPOINT_TIMEOUT_SECONDS
        ):
            await self.database_writer.commit_checkpoint(checkpoint)
        # All model operations are serialized under _processing_lock. The model
        # executor is idle while this durable progress marker is published.
        self.detector.primary_service.last_checkpoint = checkpoint["processed_count"]
        self._checkpoint_phase = phase
        self._checkpoint_gap = gap
        self._checkpoint_saved_monotonic = time.monotonic()
        self._checkpoint_received_count = processor.received_message_count
        self.recovery_status.update(
            saved_processed_count=checkpoint["processed_count"],
            saved_at=checkpoint["saved_at"].isoformat(),
            maximum_normal_rollback_samples=self.config.checkpoint_interval,
            input_recovery="live_only_with_possible_gap",
        )

    def _freeze_checkpoint(self, force: bool):
        """Run model refresh and byte serialization on the serial model owner."""
        codec = self._checkpoint_codec
        primary = self.detector.primary_service
        refresh = getattr(primary, "refresh_background_state", None)
        if refresh is not None:
            refresh()
        state = primary.export_checkpoint()
        phase = state.get("static_state", state.get("adaptive_state"))
        due = (
            primary.processed_count - primary.last_checkpoint
            >= self.config.checkpoint_interval
        )
        coverage = getattr(self.mqtt_client, "coverage", None)
        coverage_state = (
            coverage.snapshot().model_dump(mode="json")
            if coverage is not None
            else self._restored_coverage
        )
        gap = (
            coverage_state.get("dropped_message_count", 0),
            coverage_state.get("possible_gap_count", 0),
            coverage_state.get("last_gap_at"),
        )
        runtime = get_radar_checkpoint_settings()
        time_due = (
            time.monotonic() - self._checkpoint_saved_monotonic
            >= runtime.RADAR_CHECKPOINT_MAX_INTERVAL_SECONDS
        ) and (
            primary.processed_count != primary.last_checkpoint
            or self.message_processor.received_message_count
            != self._checkpoint_received_count
        )
        if not (
            force
            or due
            or time_due
            or gap != self._checkpoint_gap
            or phase != self._checkpoint_phase
        ):
            return None
        processor = ProcessorCheckpoint.model_validate(
            {
                name: getattr(self.message_processor, name)
                for name in ProcessorCheckpoint.model_fields
            }
        )
        checkpoint = codec.encode(
            RuntimeCheckpoint(
                detector=state,
                processor=processor,
                coverage=CoverageCheckpoint(data=coverage_state),
                observation_watermarks=self.message_processor.export_observation_watermarks(),
            )
        )
        return checkpoint, processor, phase, gap

    async def _checkpoint_loop(self) -> None:
        """Persist background fit transitions even when no new input arrives."""
        try:
            while not self.shutdown_event.is_set():
                await asyncio.sleep(min(self.config.health_check_interval, 5.0))
                async with self._processing_lock:
                    if self._checkpoint_codec is not None:
                        await self._checkpoint_if_due()
                    elif self._detector_runtime is not None:
                        await self._detector_runtime.refresh()
        except asyncio.CancelledError:
            raise
        except FatalExecutionError as error:
            await self._fail_execution(error)
        except Exception as error:
            self._fatal_error = error
            self.shutdown_event.set()
            logger.exception("event=radar.checkpoint_loop_failed")

    async def run(self):
        """Run the RADAR service with signal handling"""

        # Set up signal handlers
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating graceful shutdown")
            self.shutdown_event.set()

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            # Start the service
            await self.start()

            # Keep running until shutdown
            await self.shutdown_event.wait()
            if self._fatal_error is not None:
                raise RuntimeError(
                    "RADAR stopped after a managed persistence failure"
                ) from self._fatal_error

        except Exception as e:
            logger.error(f"Unexpected error in RADAR service: {e}", exc_info=True)
            raise
        finally:
            # Ensure cleanup
            await self.stop()

    def get_health_status(self) -> RadarHealthStatus:
        """Get comprehensive health status using HealthMonitor."""
        return self.health_monitor.get_health_status()


# Global service instance
_radar_service: RadarService | None = None


def get_radar_service() -> RadarService:
    """Get the global RADAR service instance"""
    global _radar_service
    if _radar_service is None:
        _radar_service = RadarService()
    return _radar_service
