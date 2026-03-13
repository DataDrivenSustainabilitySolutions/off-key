"""
Message Processor for RADAR Service

Handles MQTT message processing pipeline:
- Payload parsing and validation
- Feature alignment for multi-sensor scenarios
- Anomaly detection coordination
- Result persistence
"""

import time
from typing import Optional, Dict, Any, Tuple

from off_key_core.config.logs import logger

from .models import MQTTMessage, AnomalyResult
from .detector import ResilientAnomalyDetector, SecurityValidator, MemoryManager
from .state_cache import SensorStateCache, AlignmentUpdate
from .topic_parser import TopicParser


class MessageProcessingError(Exception):
    """Exception raised during message processing."""

    pass


class InvalidPayloadError(MessageProcessingError):
    """Exception raised when payload is invalid JSON."""

    pass


class ValidationError(MessageProcessingError):
    """Exception raised when payload fails security validation."""

    pass


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
        detector: ResilientAnomalyDetector,
        security_validator: SecurityValidator,
        memory_manager: MemoryManager,
        state_cache: Optional[SensorStateCache] = None,
        required_sensors: Optional[set] = None,
        sensor_key_strategy: str = "full_hierarchy",
    ):
        """
        Initialize message processor.

        Args:
            detector: Anomaly detection component
            security_validator: Input validation component
            memory_manager: Memory management component
            state_cache: Optional sensor state cache for alignment
            required_sensors: Set of required sensors for alignment
            sensor_key_strategy: Feature key extraction strategy for MQTT hierarchy.
                Allowed values: "full_hierarchy", "top_level", "leaf".
        """
        self.detector = detector
        self.security_validator = security_validator
        self.memory_manager = memory_manager
        self.state_cache = state_cache
        self.required_sensors = required_sensors or set()
        self.sensor_key_strategy = self._validate_sensor_key_strategy(
            sensor_key_strategy
        )

        # Metrics
        self.message_count = 0
        self.anomaly_count = 0
        self.error_count = 0

        self._log_context = {"component": "message_processor"}

    @classmethod
    def _validate_sensor_key_strategy(cls, value: str) -> str:
        """Validate sensor key strategy at construction time for clearer errors."""
        normalized = value.strip().lower()
        if normalized not in cls.SENSOR_KEY_STRATEGIES:
            allowed = ", ".join(sorted(cls.SENSOR_KEY_STRATEGIES))
            raise ValueError(f"sensor_key_strategy must be one of: {allowed}")
        return normalized

    async def process_message(self, message: MQTTMessage) -> Optional[AnomalyResult]:
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
                return None

            # Step 2: Validate and sanitize
            sanitized_data = self._sanitize_payload(data, message)
            if sanitized_data is None:
                return None

            # Step 3: Extract metadata
            charger_id = TopicParser.extract_charger_id(message.topic, payload=data)
            sensor_type = TopicParser.extract_sensor_type(
                message.topic,
                sensor_key_strategy=self.sensor_key_strategy,
                payload=data,
            )

            # Step 4: Align features (for multi-sensor)
            aligned_features, alignment_context = self._align_features(
                charger_id, sensor_type, sanitized_data
            )
            if aligned_features is None:
                return None

            # Step 5: Run anomaly detection
            result = self._detect_anomaly(
                aligned_features,
                message,
                charger_id,
                alignment_context=alignment_context,
            )

            # Step 6: Update metrics
            self._record_metrics(start_time, result)

            # Step 7: Memory management
            self._maybe_cleanup_memory()

            return result

        except InvalidPayloadError as e:
            logger.debug(
                "event=radar.message_invalid_payload topic=%s error=%s",
                message.topic,
                str(e),
            )
            self.error_count += 1
            return None
        except ValidationError as e:
            logger.debug(
                "event=radar.message_validation_failed topic=%s error=%s",
                message.topic,
                str(e),
            )
            self.error_count += 1
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
            return None

    def _parse_payload(self, message: MQTTMessage) -> Optional[Dict[str, Any]]:
        """Parse raw MQTT payload into JSON."""
        try:
            return message.get_json_payload()
        except ValueError as e:
            raise InvalidPayloadError(str(e)) from e

    def _sanitize_payload(
        self, data: Dict[str, Any], message: MQTTMessage
    ) -> Optional[Dict[str, float]]:
        """Validate and sanitize incoming message payload."""
        try:
            sanitized = self.security_validator.validate_and_sanitize(data)
            if not sanitized:
                logger.debug(
                    f"No valid features in message from {message.topic}",
                    extra=self._log_context,
                )
                return None
            return sanitized
        except ValueError as e:
            raise ValidationError(str(e)) from e

    def _align_features(
        self,
        charger_id: Optional[str],
        sensor_type: Optional[str],
        data: Dict[str, float],
    ) -> Tuple[Optional[Dict[str, float]], Dict[str, Any]]:
        """Align multi-sensor streams if required."""
        normalized_data = self._normalize_sensor_reading(sensor_type, data)

        # Skip alignment if no cache or only single sensor subscribed
        # Single-sensor mode: use normalized sensor-keyed feature.
        if not self.state_cache or not self.required_sensors:
            return normalized_data, {
                "alignment_status": "direct_pass_through",
                "aligned_vector": False,
                "required_sensor_count": len(self.required_sensors),
                "sensor_ages": {},
            }
        if len(self.required_sensors) <= 1:
            return normalized_data, {
                "alignment_status": "direct_pass_through",
                "aligned_vector": False,
                "required_sensor_count": len(self.required_sensors),
                "sensor_ages": {},
            }

        if not (charger_id and sensor_type):
            return normalized_data, {
                "alignment_status": "direct_pass_through",
                "aligned_vector": False,
                "required_sensor_count": len(self.required_sensors),
                "sensor_ages": {},
            }

        alignment_update: AlignmentUpdate = self.state_cache.update_with_status(
            charger_id,
            sensor_type,
            normalized_data,
        )
        base_context: Dict[str, Any] = {
            "alignment_status": alignment_update.status,
            "aligned_vector": bool(
                alignment_update.features and len(alignment_update.features) > 1
            ),
            "required_sensor_count": len(self.required_sensors),
            "required_sensors": sorted(self.required_sensors),
            "sensor_ages": alignment_update.sensor_ages,
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
    def _normalize_sensor_reading(
        sensor_type: Optional[str], data: Dict[str, float]
    ) -> Dict[str, float]:
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
        features: Dict[str, float],
        message: MQTTMessage,
        charger_id: Optional[str],
        alignment_context: Optional[Dict[str, Any]] = None,
    ) -> AnomalyResult:
        """Run the anomaly detector and return result."""
        result = self.detector.process_with_resilience(
            features, topic=message.topic, charger_id=charger_id
        )
        result.context = result.context or {}
        result.context["alignment"] = alignment_context or {}
        sensor_ages = (alignment_context or {}).get("sensor_ages")
        if isinstance(sensor_ages, dict):
            result.context["sensor_ages"] = sensor_ages
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
            score_window = (result.context or {}).get("score_window", {})
            alignment_context = (result.context or {}).get("alignment", {})
            zscore = score_window.get("zscore")
            window_mean = score_window.get("window_mean", score_window.get("mean"))
            window_std = score_window.get("window_std", score_window.get("std_dev"))
            history_count = score_window.get("history_count")
            sensor_ages = alignment_context.get("sensor_ages", {})
            if result.severity in ["high", "critical"]:
                logger.warning(
                    "event=radar.anomaly_detected score=%.3f \
                         zscore=%s severity=%s charger=%s",
                    result.anomaly_score,
                    zscore,
                    result.severity,
                    result.charger_id,
                    extra={
                        **self._log_context,
                        "anomaly_score": result.anomaly_score,
                        "severity": result.severity,
                        "topic": result.topic,
                        "charger_id": result.charger_id,
                        "zscore": zscore,
                        "window_mean": window_mean,
                        "window_std": window_std,
                        "history_count": history_count,
                        "sensor_ages": sensor_ages,
                    },
                )
            else:
                logger.debug(
                    "event=radar.anomaly_detected score=%.3f \
                         zscore=%s severity=%s charger=%s",
                    result.anomaly_score,
                    zscore,
                    result.severity,
                    result.charger_id,
                    extra={
                        **self._log_context,
                        "anomaly_score": result.anomaly_score,
                        "severity": result.severity,
                        "charger_id": result.charger_id,
                        "zscore": zscore,
                        "window_mean": window_mean,
                        "window_std": window_std,
                        "history_count": history_count,
                        "sensor_ages": sensor_ages,
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

    def get_metrics(self) -> Dict[str, Any]:
        """Get current processing metrics."""
        return {
            "message_count": self.message_count,
            "anomaly_count": self.anomaly_count,
            "error_count": self.error_count,
            "anomaly_rate": self.anomaly_count / max(self.message_count, 1),
            "error_rate": self.error_count / max(self.message_count, 1),
        }
