"""
Message Processor for RADAR Service

Handles MQTT message processing pipeline:
- Payload parsing and validation
- Feature alignment for multi-sensor scenarios
- Anomaly detection coordination
- Result persistence
"""

import time
from datetime import UTC, datetime
from typing import Any

from off_key_core.config.logs import logger
from off_key_core.utils.timestamps import parse_utc_timestamp

from .activity import ActivityTracker
from .coverage import CoverageTracker
from .detector_handle import DetectorHandle
from .execution_errors import FatalExecutionError, ObservationRejected
from .feature_validation import TelemetryFeatureValidator
from .memory import MemoryManager
from .models import AnomalyResult, MQTTMessage
from .state_cache import AlignmentUpdate, SensorStateCache
from .topic_parser import TopicParser


class MessageProcessingError(Exception):
    """Exception raised during message processing."""


class InvalidPayloadError(MessageProcessingError):
    """Exception raised when payload is invalid JSON."""


class ValidationError(MessageProcessingError):
    """Exception raised when payload fails security validation."""


class MessageProcessor:
    """
    Processes MQTT messages through the anomaly detection pipeline.

    Responsibilities:
    - Parse and validate incoming messages
    - Align multi-sensor data streams
    - Coordinate with anomaly detector
    - Track processing metrics
    """

    SENSOR_KEY_STRATEGIES = TopicParser.SENSOR_KEY_STRATEGIES

    def __init__(
        self,
        detector: DetectorHandle,
        feature_validator: TelemetryFeatureValidator,
        memory_manager: MemoryManager,
        state_cache: SensorStateCache | None = None,
        required_sensors: set | None = None,
        sensor_key_strategy: str = "full_hierarchy",
        coverage: CoverageTracker | None = None,
        observation_max_age_seconds: float = 30.0,
        observation_future_tolerance_seconds: float = 5.0,
        sensor_freshness_seconds: float = 30.0,
    ):
        """
        Initialize message processor.

        Args:
            detector: Anomaly detection component
            feature_validator: Input validation component
            memory_manager: Memory management component
            state_cache: Optional sensor state cache for alignment
            required_sensors: Set of required sensors for alignment
            sensor_key_strategy: Feature key extraction strategy for MQTT hierarchy.
                Allowed values: "full_hierarchy", "top_level", "leaf".
        """
        self.detector = detector
        self.feature_validator = feature_validator
        self.memory_manager = memory_manager
        self.coverage = coverage
        self.state_cache = state_cache
        self.required_sensors = required_sensors or set()
        self.activity = ActivityTracker(self.required_sensors)
        self._direct_state_cache = SensorStateCache(
            set(),
            max_sensor_age_seconds=sensor_freshness_seconds,
            observation_max_age_seconds=observation_max_age_seconds,
            observation_future_tolerance_seconds=observation_future_tolerance_seconds,
        )
        self.sensor_key_strategy = self._validate_sensor_key_strategy(
            sensor_key_strategy
        )

        # Metrics
        self.received_message_count = 0
        self.message_count = 0
        self.anomaly_count = 0
        self.error_count = 0
        self.last_alignment_status: str | None = None

        self._log_context = {"component": "message_processor"}

    @classmethod
    def _validate_sensor_key_strategy(cls, value: str) -> str:
        """Validate sensor key strategy at construction time for clearer errors."""
        normalized = value.strip().lower()
        if normalized not in cls.SENSOR_KEY_STRATEGIES:
            allowed = ", ".join(sorted(cls.SENSOR_KEY_STRATEGIES))
            raise ValueError(f"sensor_key_strategy must be one of: {allowed}")
        return normalized

    def process_message_sync(self, message: MQTTMessage) -> AnomalyResult | None:
        """
        Process an MQTT message through the detection pipeline.

        Args:
            message: Incoming MQTT message

        Returns:
            AnomalyResult if processing succeeded, None if skipped
        """
        start_time = time.time()

        try:
            # Step 1: Parse payload
            data = self._parse_payload(message)
            if data is None:
                self._record_coverage_drop("invalid_payload")
                return None
            sample_timestamp = self._resolve_sample_timestamp(data, message)

            # Step 2: Validate and sanitize
            sanitized_data = self._sanitize_payload(data, message)
            if sanitized_data is None:
                self._record_coverage_drop("invalid_features")
                return None
            self.received_message_count += 1

            # Step 3: Extract metadata
            charger_id = TopicParser.extract_charger_id(message.topic, payload=data)
            sensor_type = TopicParser.extract_sensor_type(
                message.topic,
                sensor_key_strategy=self.sensor_key_strategy,
                payload=data,
            )

            # Step 4: Align features (for multi-sensor)
            aligned_features, alignment_context = self._align_features(
                charger_id,
                sensor_type,
                sanitized_data,
                sample_timestamp=sample_timestamp,
                received_monotonic=self._receipt_monotonic(message),
            )
            self.last_alignment_status = alignment_context.get("alignment_status")
            if self.last_alignment_status != "observation_rejected":
                self.activity.record_input(sensor_type, message)
            if aligned_features is None:
                return None

            # Step 5: Run anomaly detection
            result = self._detect_anomaly(
                aligned_features,
                message,
                charger_id,
                alignment_context=alignment_context,
            )
            self.activity.record_result(result)

            # Step 6: Update metrics
            self._record_metrics(start_time, result)

            # Step 7: Memory management
            self._maybe_cleanup_memory()

            return result

        except FatalExecutionError:
            self.error_count += 1
            self._record_coverage_drop("fatal_execution")
            raise
        except ObservationRejected:
            self.error_count += 1
            self._record_coverage_drop("pipeline_observation_rejected")
            return None
        except (InvalidPayloadError, ValidationError) as e:
            logger.debug(
                "event=radar.message_validation_failed topic=%s error=%s",
                message.topic,
                str(e),
            )
            self.error_count += 1
            self._record_coverage_drop(
                "invalid_payload"
                if isinstance(e, InvalidPayloadError)
                else "invalid_features"
            )
            return None
        except Exception as e:
            logger.error(
                "event=radar.message_processing_failed topic=%s error=%s",
                message.topic,
                str(e),
                exc_info=True,
                extra=self._log_context,
            )
            self.error_count += 1
            self._record_coverage_drop("processing_error")
            return None

    def _record_coverage_drop(self, reason: str) -> None:
        if self.coverage is not None:
            self.coverage.record_drop(reason)

    def _parse_payload(self, message: MQTTMessage) -> dict[str, Any] | None:
        """Parse raw MQTT payload into JSON."""
        try:
            return message.get_json_payload()
        except ValueError as e:
            raise InvalidPayloadError(str(e)) from e

    def _sanitize_payload(
        self, data: dict[str, Any], message: MQTTMessage
    ) -> dict[str, float] | None:
        """Validate and sanitize incoming message payload."""
        try:
            sanitized = self.feature_validator.validate_and_sanitize(data)
            if not sanitized:
                logger.debug(
                    f"No valid features in message from {message.topic}",
                    extra=self._log_context,
                )
                return None
            return sanitized
        except ValueError as e:
            raise ValidationError(str(e)) from e

    @staticmethod
    def _resolve_sample_timestamp(data: dict[str, Any], message: MQTTMessage) -> float:
        """Use the same event timestamp that the telemetry service persists."""
        timestamp_value = data.get("timestamp")
        if timestamp_value is not None:
            try:
                return parse_utc_timestamp(timestamp_value).timestamp()
            except (ValueError, TypeError, OSError, OverflowError) as error:
                raise ValidationError(
                    f"Invalid timestamp format: {timestamp_value}"
                ) from error

        received_at = message.timestamp or datetime.now(UTC)
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=UTC)
        return received_at.astimezone(UTC).timestamp()

    def _align_features(
        self,
        charger_id: str | None,
        sensor_type: str | None,
        data: dict[str, float],
        sample_timestamp: float | None = None,
        received_monotonic: float | None = None,
    ) -> tuple[dict[str, float] | None, dict[str, Any]]:
        """Align multi-sensor streams if required."""
        normalized_data = self._normalize_sensor_reading(sensor_type, data)

        direct = (
            not self.state_cache
            or len(self.required_sensors) <= 1
            or not (charger_id and sensor_type)
        )
        cache = self._direct_state_cache if direct else self.state_cache
        receipt = (
            {"received_monotonic": received_monotonic}
            if received_monotonic is not None
            else {}
        )
        alignment_update: AlignmentUpdate = cache.update_with_status(
            charger_id or "",
            sensor_type or "",
            normalized_data,
            sample_timestamp=sample_timestamp,
            **receipt,
        )
        if alignment_update.status == "observation_rejected":
            self._record_coverage_drop(alignment_update.rejection_reason)
            return None, {
                "alignment_status": alignment_update.status,
                "rejection_reason": alignment_update.rejection_reason,
            }
        if direct:
            return normalized_data, self._direct_alignment_context(
                sensor_type, alignment_update.sample_timestamp
            )
        base_context: dict[str, Any] = {
            "alignment_status": alignment_update.status,
            "aligned_vector": bool(
                alignment_update.features and len(alignment_update.features) > 1
            ),
            "required_sensor_count": len(self.required_sensors),
            "required_sensors": sorted(self.required_sensors),
            "sensor_ages": alignment_update.sensor_ages,
            "input_timestamps": alignment_update.input_timestamps,
            "sample_timestamp": alignment_update.sample_timestamp,
        }

        if alignment_update.status == "waiting_for_all":
            logger.debug(
                "Sensor alignment waiting_for_all",
                extra={
                    **self._log_context,
                    "event": "waiting_for_all",
                    "charger_id": charger_id,
                    "sensor_type": sensor_type,
                    "missing_sensors": list(alignment_update.missing_sensors),
                    "sensor_ages": alignment_update.sensor_ages,
                },
            )
            base_context["missing_sensors"] = list(alignment_update.missing_sensors)
            return None, base_context

        if alignment_update.status == "stale_sensor_block":
            logger.warning(
                "Sensor alignment blocked by stale sensor data",
                extra={
                    **self._log_context,
                    "event": "stale_sensor_block",
                    "charger_id": charger_id,
                    "sensor_type": sensor_type,
                    "stale_sensors": list(alignment_update.stale_sensors),
                    "sensor_ages": alignment_update.sensor_ages,
                },
            )
            base_context["stale_sensors"] = list(alignment_update.stale_sensors)
            return None, base_context

        if alignment_update.status == "waiting_for_barrier":
            logger.debug(
                "Sensor alignment waiting_for_barrier",
                extra={
                    **self._log_context,
                    "event": "waiting_for_barrier",
                    "charger_id": charger_id,
                    "sensor_type": sensor_type,
                    "pending_sensors": list(alignment_update.pending_sensors),
                    "sensor_ages": alignment_update.sensor_ages,
                },
            )
            base_context["pending_sensors"] = list(alignment_update.pending_sensors)
            return None, base_context

        if alignment_update.status == "aligned_emit":
            logger.debug(
                "Aligned multivariate feature vector emitted",
                extra={
                    **self._log_context,
                    "event": "aligned_emit",
                    "charger_id": charger_id,
                    "sensor_type": sensor_type,
                    "required_sensors": sorted(self.required_sensors),
                    "sensor_ages": alignment_update.sensor_ages,
                },
            )

        return alignment_update.features, base_context

    @staticmethod
    def _receipt_monotonic(message: MQTTMessage) -> float | None:
        if message.received_monotonic is not None:
            return message.received_monotonic
        if message.timestamp is None:
            return None
        received_at = message.timestamp
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=UTC)
        age = max((datetime.now(UTC) - received_at).total_seconds(), 0.0)
        return time.monotonic() - age

    def _direct_alignment_context(
        self,
        sensor_type: str | None,
        sample_timestamp: float | None = None,
    ) -> dict[str, Any]:
        """Build alignment context for messages that bypass multi-sensor alignment."""
        input_timestamps = (
            {sensor_type: sample_timestamp}
            if sensor_type and isinstance(sample_timestamp, int | float)
            else {}
        )
        return {
            "alignment_status": "direct_pass_through",
            "aligned_vector": False,
            "required_sensor_count": len(self.required_sensors),
            "sensor_ages": {},
            "input_timestamps": input_timestamps,
            "sample_timestamp": sample_timestamp,
        }

    @staticmethod
    def _normalize_sensor_reading(
        sensor_type: str | None, data: dict[str, float]
    ) -> dict[str, float]:
        """Normalize payload to a stable feature key based on sensor type.

        Priority order: sensor_type key, then "value", then first available key.
        """
        if not sensor_type or not data:
            return data

        if sensor_type in data:
            return {sensor_type: float(data[sensor_type])}

        if "value" in data:
            return {sensor_type: float(data["value"])}

        first_key = next(iter(data))
        return {sensor_type: float(data[first_key])}

    def _detect_anomaly(
        self,
        features: dict[str, float],
        message: MQTTMessage,
        charger_id: str | None,
        alignment_context: dict[str, Any] | None = None,
    ) -> AnomalyResult:
        """Run the anomaly detector and return result."""
        result = self.detector.process(
            features, topic=message.topic, charger_id=charger_id
        )
        result.context = result.context or {}
        result.context["alignment"] = alignment_context or {}
        sensor_ages = (alignment_context or {}).get("sensor_ages")
        if isinstance(sensor_ages, dict):
            result.context["sensor_ages"] = sensor_ages
        input_timestamps = (alignment_context or {}).get("input_timestamps")
        sample_timestamp = (alignment_context or {}).get("sample_timestamp")
        if isinstance(input_timestamps, dict):
            finite_input_timestamps = [
                float(timestamp)
                for timestamp in input_timestamps.values()
                if isinstance(timestamp, int | float)
            ]
            if finite_input_timestamps:
                sample_timestamp = max(finite_input_timestamps)
        if isinstance(sample_timestamp, int | float):
            canonical_dt = datetime.fromtimestamp(float(sample_timestamp), tz=UTC)
            result.timestamp = canonical_dt
            result.context["canonical_sample_timestamp"] = canonical_dt.isoformat()
        metadata = getattr(
            self.detector.primary_service, "attach_observation_metadata", None
        )
        if callable(metadata):
            try:
                metadata(result.timestamp, input_timestamps or {})
            except Exception:
                logger.exception("event=radar.pipeline_diagnostic_metadata_failed")
        self.message_count += 1
        if result.is_anomaly:
            self.anomaly_count += 1
        return result

    def _record_metrics(self, start_time: float, result: AnomalyResult) -> None:
        """Log processing activity and anomalies."""
        # Log first message to confirm data is flowing
        if self.message_count == 1:
            logger.info(
                f"First message received and processed from {result.topic}",
                extra={
                    **self._log_context,
                    "charger_id": result.charger_id,
                    "anomaly_score": result.anomaly_score,
                },
            )

        # Log all anomalies
        if result.is_anomaly:
            alignment_context = (result.context or {}).get("alignment", {})
            sensor_ages = alignment_context.get("sensor_ages", {})
            if result.severity in ["high", "critical"]:
                logger.warning(
                    "event=radar.anomaly_detected score=%.3f severity=%s charger=%s",
                    result.anomaly_score,
                    result.severity,
                    result.charger_id,
                    extra={
                        **self._log_context,
                        "anomaly_score": result.anomaly_score,
                        "severity": result.severity,
                        "topic": result.topic,
                        "charger_id": result.charger_id,
                        "sensor_ages": sensor_ages,
                        "alignment_status": alignment_context.get("alignment_status"),
                        "canonical_sample_timestamp": (result.context or {}).get(
                            "canonical_sample_timestamp"
                        ),
                    },
                )
            else:
                logger.debug(
                    "event=radar.anomaly_detected score=%.3f severity=%s charger=%s",
                    result.anomaly_score,
                    result.severity,
                    result.charger_id,
                    extra={
                        **self._log_context,
                        "anomaly_score": result.anomaly_score,
                        "severity": result.severity,
                        "charger_id": result.charger_id,
                        "sensor_ages": sensor_ages,
                        "alignment_status": alignment_context.get("alignment_status"),
                        "canonical_sample_timestamp": (result.context or {}).get(
                            "canonical_sample_timestamp"
                        ),
                    },
                )

    def _maybe_cleanup_memory(self) -> None:
        """Trigger periodic memory cleanup."""
        if self.memory_manager.should_cleanup():
            freed = self.memory_manager.force_cleanup()
            logger.debug(
                "event=radar.memory_cleanup freed_mb=%.1f",
                freed,
                extra=self._log_context,
            )

    def export_observation_watermarks(self) -> dict[str, dict[str, float]]:
        """Persist accepted observation times without retaining partial vectors."""
        watermarks: dict[str, dict[str, float]] = {}
        for cache in (self._direct_state_cache, self.state_cache):
            if cache is None:
                continue
            for entity, sensors in cache.export_watermarks().items():
                target = watermarks.setdefault(entity, {})
                for sensor, timestamp in sensors.items():
                    target[sensor] = max(target.get(sensor, timestamp), timestamp)
        return watermarks

    def restore_observation_watermarks(
        self,
        payload: dict[str, dict[str, float]],
    ) -> None:
        """Restore rejection history while requiring new input for each vector."""
        for cache in (self._direct_state_cache, self.state_cache):
            if cache is not None:
                cache.restore_watermarks(payload)

    def get_metrics(self) -> dict[str, Any]:
        """Get current processing metrics."""
        return {
            "message_count": self.received_message_count,
            "processed_message_count": self.message_count,
            "anomaly_count": self.anomaly_count,
            "error_count": self.error_count,
            "anomaly_rate": self.anomaly_count / max(self.message_count, 1),
            "error_rate": self.error_count / max(self.received_message_count, 1),
            "last_alignment_status": self.last_alignment_status,
            "activity": self.activity.snapshot(),
        }
