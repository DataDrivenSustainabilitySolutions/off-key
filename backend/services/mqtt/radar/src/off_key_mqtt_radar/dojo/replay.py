"""Run one detection design over historical points, as a live monitor would.

Each point goes through the same message processor, alignment cache and
detector as live MQTT input. Only the clocks differ: both read the time of the
point being replayed, so freshness and skew limits measure the data's own
time instead of the wall clock. Background fitting is awaited, so no point is
discarded while a static baseline trains and a replay is reproducible.
"""

import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from off_key_core.models.dojo_runs import DOJO_SENSOR_KEY_STRATEGY
from off_key_core.schemas.dojo import RunAlignment
from off_key_core.schemas.pipelines import PipelineExecutionConfig

from ..config.config import AnomalyDetectionConfig
from ..coverage import CoverageTracker
from ..detector_handle import DetectorHandle
from ..detector_services import detector_service_class
from ..feature_validation import TelemetryFeatureValidator
from ..memory import MemoryManager
from ..message_processor import MessageProcessor
from ..models import AnomalyResult, MQTTMessage, inference_key, strategy_context_key
from ..state_cache import SensorStateCache
from ..topic_parser import TopicParser

SENSOR_KEY_STRATEGY = DOJO_SENSOR_KEY_STRATEGY


@dataclass(frozen=True)
class ReplayResult:
    sequence: int
    timestamp: datetime
    phase: str
    score: float | None
    threshold: float | None
    alarm: bool


class _ReplayClock:
    """Both clocks of the alignment cache, set to the replayed point's time."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def detection_config(
    execution: PipelineExecutionConfig, alignment: RunAlignment, memory_limit_mb: int
) -> AnomalyDetectionConfig:
    return AnomalyDetectionConfig.model_validate(
        {
            "pipeline": execution.model_dump(mode="json"),
            "sensor_key_strategy": SENSOR_KEY_STRATEGY,
            "sensor_freshness_seconds": alignment.freshness_seconds,
            "observation_max_age_seconds": alignment.freshness_seconds,
            # Every point arrives exactly at its own time.
            "observation_future_tolerance_seconds": 0.0,
            "alignment_max_skew_seconds": alignment.max_skew_seconds,
            "memory_limit_mb": memory_limit_mb,
        }
    )


class Replay:
    """Feed points in time order; collect one compact row per detector result."""

    def __init__(self, config: AnomalyDetectionConfig) -> None:
        self._clock = _ReplayClock()
        required = TopicParser.derive_required_sensors(
            config.subscription_topics, sensor_key_strategy=SENSOR_KEY_STRATEGY
        )
        cache = (
            SensorStateCache(
                required,
                max_sensor_age_seconds=config.sensor_freshness_seconds,
                observation_max_age_seconds=config.observation_max_age_seconds,
                observation_future_tolerance_seconds=(
                    config.observation_future_tolerance_seconds
                ),
                alignment_max_skew_seconds=config.alignment_max_skew_seconds,
                clock=self._clock,
                monotonic=self._clock,
            )
            if required
            else None
        )
        service_cls = detector_service_class(config)
        self.detector = DetectorHandle(service_cls(config))
        self.coverage = CoverageTracker()
        self.processor = MessageProcessor(
            detector=self.detector,
            feature_validator=TelemetryFeatureValidator(),
            memory_manager=MemoryManager(max_memory_mb=config.memory_limit_mb),
            state_cache=cache,
            required_sensors=required,
            sensor_key_strategy=SENSOR_KEY_STRATEGY,
            coverage=self.coverage,
            observation_max_age_seconds=config.observation_max_age_seconds,
            observation_future_tolerance_seconds=(
                config.observation_future_tolerance_seconds
            ),
            sensor_freshness_seconds=config.sensor_freshness_seconds,
            clock=self._clock,
            monotonic=self._clock,
        )
        self.sequence = 0
        self.alarm_count = 0
        self._waiting: Counter[str] = Counter()

    def step(self, topic: str, timestamp: float, value: float) -> ReplayResult | None:
        """Replay one point. A detector failure raises FatalExecutionError."""
        self._clock.now = timestamp
        message = MQTTMessage(
            topic=topic,
            payload=json.dumps({"value": value, "timestamp": timestamp}).encode(),
            timestamp=datetime.fromtimestamp(timestamp, UTC),
            received_monotonic=timestamp,
        )
        result = self.processor.process_message_sync(message)
        self.detector.primary_service.wait_for_background()
        if result is None:
            status = self.processor.last_alignment_status
            # Rejections are counted by the coverage tracker with their reason.
            if status and status not in {"observation_rejected", "aligned_emit"}:
                self._waiting[status] += 1
            return None
        return self._row(result)

    def _row(self, result: AnomalyResult) -> ReplayResult:
        self.sequence += 1
        key = strategy_context_key(result.context)
        context = (result.context or {}).get(key, {}) if key else {}
        scored = inference_key(result.context) is not None
        score = None
        if scored:
            score = _finite(
                context.get("p_value")
                if key == "static_conformal"
                else context.get("anomaly_score", result.anomaly_score)
            )
        if result.is_anomaly:
            self.alarm_count += 1
        return ReplayResult(
            sequence=self.sequence,
            timestamp=result.timestamp,
            phase=str(context.get("phase") or "unknown"),
            score=score,
            # A static baseline alarms on a martingale over its p-values, so
            # only an adaptive score has a threshold of its own.
            threshold=(
                _finite(context.get("threshold"))
                if scored and key == "adaptive_stream"
                else None
            ),
            alarm=bool(result.is_anomaly),
        )

    def stats(self) -> dict[str, int]:
        """Observations without a result, by reason."""
        dropped = self.coverage.snapshot().dropped_by_reason
        return dict(sorted({**self._waiting, **dropped}.items()))

    def close(self) -> None:
        self.detector.primary_service.shutdown()
