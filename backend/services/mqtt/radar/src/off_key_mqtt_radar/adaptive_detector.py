"""Aberrant-backed score-then-learn adaptive pipeline runs: readiness-aware
feature graphs that warm transforms without contaminating the model or its
calibration."""

import hashlib
import json
import logging
import math
import time
from collections import deque
from datetime import UTC, datetime
from enum import Enum
from typing import Any, NoReturn

import numpy as np
from aberrant import __version__ as aberrant_version
from aberrant.base import ModelProtocol
from aberrant.catalog import ResolvedDetectorConfig
from aberrant.compose import (
    GraphExecutionError,
    GraphPipeline,
    GraphStateUncertainError,
)
from off_key_core.models import ABERRANT_VERSION
from off_key_core.schemas.radar import AdaptiveStreamConfig

from .config.config import AnomalyDetectionConfig
from .execution_errors import FatalExecutionError, ObservationRejected
from .fusion import RankFusion, threshold_count
from .memory import process_rss_mb
from .models import AnomalyResult, inference_key
from .pipelines.adapters import adaptive_graph, resolved_detector_config
from .pipelines.execution import PipelineExecutionMixin
from .pipelines.prepare import Withheld


class AdaptiveStreamState(Enum):
    WARMUP = "warmup"
    CALIBRATING = "calibrating"
    OPERATIONAL = "operational"
    FAILED = "failed"


class AdaptiveStreamDetectionService(PipelineExecutionMixin):
    """Online detector with bounded warm-up and frozen score calibration."""

    def __init__(
        self,
        config: AnomalyDetectionConfig,
        checkpoint: dict[str, Any] | None = None,
    ) -> None:
        self._init_pipeline_execution(config)
        if self.plan.execution.definition.strategy != "adaptive_stream":
            raise ValueError("Adaptive execution requires an adaptive pipeline")
        self._scored_features: dict[str, float] | None = None
        # The bound readings of the current observation, before any Prepare step.
        self._bound: dict[str, float] = {}
        self.config = config
        adaptive_config = config.monitoring
        if not isinstance(adaptive_config, AdaptiveStreamConfig):
            raise ValueError("adaptive_stream_config is required")
        self.adaptive_config: AdaptiveStreamConfig = adaptive_config
        if aberrant_version != ABERRANT_VERSION:
            raise ValueError(
                "RADAR runtime does not match its generated Aberrant catalog"
            )
        self.logger = logging.getLogger(__name__)
        self._resolved_detectors = [
            resolved_detector_config(self.plan, identifier)
            for identifier in self.plan.detector_ids
        ]
        self._resolved_detector = self._resolved_detectors[0]
        self.detector_config = self._resolved_detector.config
        self.detector_fingerprint = self._resolved_detector.fingerprint
        self.model_capabilities = self._resolved_detector.capabilities.as_dict()
        self.schema_signature = self._build_schema_signature(config)
        self.start_time = time.time()
        self.processing_times: deque[float] = deque(maxlen=1000)
        self.training_error: str | None = None
        if checkpoint is None:
            self._initialize_fresh()
        else:
            self._restore(checkpoint)
        self._raw_unit_interval_slots = self._unit_interval_slots()
        self._report_readiness()

    def _initialize_fresh(self) -> None:
        self.state = AdaptiveStreamState.WARMUP
        self.feature_keys: list[str] = self._initial_feature_keys()
        # Validate constructors at startup, before subscribing or learning data.
        if self.plan.fused:
            self.pipelines = [
                adaptive_graph(
                    self.plan, self._observer(identifier), config, identifier
                )[0]
                for identifier, config in zip(
                    self.plan.detector_ids, self._resolved_detectors, strict=True
                )
            ]
            self.pipeline = self.pipelines[0]
        else:
            self.pipeline: ModelProtocol = self._build_pipeline(self._resolved_detector)
            self.pipelines = [self.pipeline]
        # One score per observation, or one list of scores with several detectors.
        self.calibration_scores: list = []
        self.fusion: RankFusion | None = None
        self.threshold_count: int | None = None
        self.threshold: float | None = None
        self.severity_scale = 0.0
        self.processed_count = 0
        self.warmup_count = 0
        self.calibration_count = 0
        self.operational_count = 0
        self.anomaly_count = 0
        self.last_checkpoint = 0

    def _restore(self, checkpoint: dict[str, Any]) -> None:
        if checkpoint.get("schema_signature") != self.schema_signature:
            raise ValueError("Adaptive graph checkpoint configuration is incompatible")
        self.state = AdaptiveStreamState(checkpoint["adaptive_state"])
        self.feature_keys = list(checkpoint["feature_keys"])
        if checkpoint.get("detector_fingerprint") != self.detector_fingerprint:
            raise ValueError(
                "Adaptive checkpoint detector configuration is incompatible"
            )
        if checkpoint.get("detector_config") != self.detector_config.as_dict():
            raise ValueError(
                "Adaptive checkpoint normalized configuration is incompatible"
            )
        if self.plan.fused:
            self._restore_detectors(checkpoint)
        else:
            self.pipeline = checkpoint["pipeline"]
            self.pipelines = [self.pipeline]
        self.calibration_scores = list(checkpoint.get("calibration_scores", []))
        self.fusion = None
        self.threshold_count = None
        self.threshold = checkpoint.get("threshold")
        self.severity_scale = float(checkpoint["severity_scale"])
        self.processed_count = int(checkpoint.get("processed_count", 0))
        self.warmup_count = int(checkpoint.get("warmup_count", 0))
        self.calibration_count = int(checkpoint.get("calibration_count", 0))
        self.operational_count = int(checkpoint.get("operational_count", 0))
        self.anomaly_count = int(checkpoint.get("anomaly_count", 0))
        self.last_checkpoint = self.processed_count
        self.training_error = checkpoint.get("training_error")
        if self.pipeline is None or (
            not self.feature_keys and self.processed_count != 0
        ):
            raise ValueError("Adaptive checkpoint is missing pipeline state")
        if self.state == AdaptiveStreamState.OPERATIONAL and self.threshold is None:
            raise ValueError("Operational adaptive checkpoint has no threshold")
        if any(
            not isinstance(graph, GraphPipeline) or graph.failed
            for graph in self.pipelines
        ):
            raise ValueError("Checkpoint has no usable adaptive graph")
        if self.state == AdaptiveStreamState.FAILED:
            raise ValueError("Failed adaptive executions cannot be restored")
        self._restore_prepare(checkpoint)
        if self.plan.fused:
            self._resume_detectors(checkpoint)
        else:
            self.pipeline.observer = self._observe

    def _resume_detectors(self, checkpoint: dict[str, Any]) -> None:
        for identifier, graph in zip(
            self.plan.detector_ids, self.pipelines, strict=True
        ):
            graph.observer = self._observer(identifier)
        if self.state == AdaptiveStreamState.OPERATIONAL:
            # The calibration scores give the same frozen threshold again.
            self._freeze_fusion()
            if self.threshold != checkpoint.get("threshold"):
                raise ValueError("Adaptive checkpoint threshold is inconsistent")

    def _restore_detectors(self, checkpoint: dict[str, Any]) -> None:
        """Every detector's graph, checked against its configuration."""
        expected = [item.fingerprint for item in self._resolved_detectors]
        if checkpoint.get("detector_fingerprints") != expected:
            raise ValueError(
                "Adaptive checkpoint detector configuration is incompatible"
            )
        configs = [item.config.as_dict() for item in self._resolved_detectors]
        if checkpoint.get("detector_configs") != configs:
            raise ValueError(
                "Adaptive checkpoint normalized configuration is incompatible"
            )
        pipelines = checkpoint.get("pipelines")
        if not isinstance(pipelines, list) or len(pipelines) != len(configs):
            raise ValueError("Adaptive checkpoint is missing a detector's graph")
        self.pipelines = list(pipelines)
        self.pipeline = self.pipelines[0]

    @classmethod
    def from_checkpoint_data(
        cls,
        checkpoint: dict[str, Any],
        config: AnomalyDetectionConfig,
    ) -> "AdaptiveStreamDetectionService":
        if checkpoint.get("strategy") != "adaptive_stream":
            raise ValueError("Checkpoint strategy does not match adaptive_stream")
        if checkpoint.get("aberrant_version") != aberrant_version:
            raise ValueError("Checkpoint aberrant version is incompatible")
        if checkpoint.get("schema_signature") != cls._build_schema_signature(config):
            raise ValueError("Adaptive checkpoint configuration is incompatible")
        return cls(config, checkpoint=checkpoint)

    @staticmethod
    def _build_schema_signature(config: AnomalyDetectionConfig) -> str:
        return PipelineExecutionMixin._pipeline_signature(
            AdaptiveStreamDetectionService._settings_signature(config), config
        )

    @staticmethod
    def _settings_signature(config: AnomalyDetectionConfig) -> str:
        adaptive_config = config.monitoring
        if not isinstance(adaptive_config, AdaptiveStreamConfig):
            raise ValueError("Adaptive detector requires adaptive_stream configuration")
        payload = {
            "strategy": "adaptive_stream",
            "adaptive_stream_config": adaptive_config.model_dump(
                mode="json", exclude_none=True, exclude={"strategy"}
            ),
            "subscription_topics": sorted(config.subscription_topics),
            "sensor_key_strategy": config.sensor_key_strategy,
            "sensor_freshness_seconds": config.sensor_freshness_seconds,
            "observation_max_age_seconds": config.observation_max_age_seconds,
            "observation_future_tolerance_seconds": (
                config.observation_future_tolerance_seconds
            ),
            "alignment_max_skew_seconds": config.alignment_max_skew_seconds,
            "aberrant_version": aberrant_version,
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode()).hexdigest()

    def _initial_feature_keys(self) -> list[str]:
        return sorted(slot.id for slot in self.plan.compiled.definition.input_slots)

    def _build_pipeline(self, config: ResolvedDetectorConfig) -> ModelProtocol:
        return adaptive_graph(self.plan, self._observe, config)[0]

    def process_data_point(
        self,
        data: dict[str, float],
        topic: str | None = None,
        charger_id: str | None = None,
    ) -> AnomalyResult:
        if self._execution_failed or self._pipeline_failed():
            raise FatalExecutionError(
                self.training_error or "Pipeline execution has failed"
            )
        bound = self._validated_observation(data)
        self._scored_features = None
        self._detector_results: list[dict[str, Any]] | None = None
        self._diagnose(
            self.diagnostics.begin, self.processed_count + 1, self.state.value
        )
        try:
            result = self._process(bound, topic, charger_id)
            result.raw_data = dict(data)
            result.processed_features = self._scored_features
            self._record_result(result)
            return result
        except ObservationRejected:
            raise
        except Exception as error:
            self._execution_failed = True
            self.state = AdaptiveStreamState.FAILED
            self.training_error = str(error)
            identifier = self._failure_node(error)
            self._diagnose(self.diagnostics.fail, identifier, error)
            raise FatalExecutionError(str(error), node_id=identifier) from error
        finally:
            self._diagnose(self.diagnostics.finish)

    def _validated_observation(self, data):
        try:
            if not isinstance(data, dict):
                raise ObservationRejected("Pipeline inputs must be a feature mapping")
            bound = self.plan.bind(data)
            if not all(math.isfinite(value) for value in bound.values()):
                raise ObservationRejected("Pipeline inputs must be finite")
            for slot in self._raw_unit_interval_slots:
                if not 0.0 <= bound[slot] <= 1.0:
                    raise ObservationRejected(
                        f"Raw feature {slot!r} must be in [0, 1] for this detector"
                    )
        except (TypeError, ValueError, OverflowError) as error:
            raise ObservationRejected(str(error)) from error
        return bound

    def _unit_interval_slots(self) -> frozenset[str]:
        """Readings a detector that needs [0, 1] values scores without a step."""
        return frozenset(
            slot
            for identifier, resolved in zip(
                self.plan.detector_ids, self._resolved_detectors, strict=True
            )
            if resolved.capabilities.requires_unit_interval
            for feature in self.plan.compiled.features[
                self.plan.detector_inputs[identifier]
            ]
            if feature.raw
            for slot in feature.slots
        )

    def _process(
        self,
        data: dict[str, float],
        topic: str | None,
        charger_id: str | None,
    ) -> AnomalyResult:
        # Binding has checked the schema and finiteness; failures stop the run.
        started = time.time()
        self._bound = data
        prepared = self._prepared(data)
        if isinstance(prepared, Withheld):
            self.processed_count += 1
            return self._result(
                data, 0.0, False, prepared.reason, topic, charger_id, started
            )
        return self._process_current_state(prepared, topic, charger_id, started)

    def _process_current_state(
        self,
        data: dict[str, float],
        topic: str | None,
        charger_id: str | None,
        started: float,
    ) -> AnomalyResult:
        if self.state == AdaptiveStreamState.WARMUP:
            return self._process_warmup(data, topic, charger_id, started)
        if self.state == AdaptiveStreamState.CALIBRATING:
            return self._process_calibration(data, topic, charger_id, started)
        if self.state == AdaptiveStreamState.OPERATIONAL:
            return self._process_operational(data, topic, charger_id, started)
        raise RuntimeError(self.training_error or "Adaptive detector failed")

    def _process_warmup(
        self,
        data: dict[str, float],
        topic: str | None,
        charger_id: str | None,
        started: float,
    ) -> AnomalyResult:
        self._learn(data)
        # Warm-up ends when every detector is ready: the slowest one counts.
        self.warmup_count = min(
            graph.last_learning_outcome.model_updates for graph in self.pipelines
        )
        self.processed_count += 1
        if self.warmup_count >= self.adaptive_config.training_window_size and all(
            graph.readiness.ready for graph in self.pipelines
        ):
            self.state = AdaptiveStreamState.CALIBRATING
            self.logger.info(
                "event=radar.adaptive_warmup_complete warmup_count=%s "
                "processed_count=%s",
                self.warmup_count,
                self.processed_count,
            )
        return self._result(data, 0.0, False, "warmup", topic, charger_id, started)

    def _process_calibration(
        self,
        data: dict[str, float],
        topic: str | None,
        charger_id: str | None,
        started: float,
    ) -> AnomalyResult:
        if self.plan.fused:
            return self._calibrate_fused(data, topic, charger_id, started)
        score = self._score(data)
        self._learn(data)
        self.calibration_scores.append(score)
        self.calibration_count += 1
        self.processed_count += 1
        if self.calibration_count >= self.adaptive_config.calibration_window_size:
            self.threshold = float(
                np.quantile(
                    np.asarray(self.calibration_scores, dtype=float),
                    self.adaptive_config.threshold_config.quantile,
                    method="higher",
                )
            )
            self.severity_scale = max(
                abs(self.threshold),
                max(self.calibration_scores) - min(self.calibration_scores),
            )
            self.state = AdaptiveStreamState.OPERATIONAL
            self._log_calibrated()
        return self._result(
            data, score, False, "calibration", topic, charger_id, started
        )

    def _process_operational(
        self,
        data: dict[str, float],
        topic: str | None,
        charger_id: str | None,
        started: float,
    ) -> AnomalyResult:
        if self.threshold is None:
            raise RuntimeError("Adaptive threshold is not initialized")
        if self.plan.fused:
            score, is_anomaly = self._score_fused(data)
        else:
            score = self._score(data)
            is_anomaly = score > self.threshold
        self._learn(data)
        self.operational_count += 1
        self.processed_count += 1
        if is_anomaly:
            self.anomaly_count += 1
        return self._result(
            data, score, is_anomaly, "operational", topic, charger_id, started
        )

    def _score(self, data: dict[str, float]) -> float:
        self._diagnose(self.diagnostics.select_pass, "score")
        self.diagnostics.record(self.plan.source_id, self._bound, self._bound)
        try:
            score = float(self.pipeline.score_one(data))
        except GraphExecutionError as error:
            self._rolled_back(error)
        if not math.isfinite(score):
            raise ValueError("Aberrant returned a non-finite anomaly score")
        return score

    def _learn(self, data: dict[str, float]) -> None:
        self._diagnose(self.diagnostics.select_pass, "learn")
        self.diagnostics.record(self.plan.source_id, self._bound, self._bound)
        if self.plan.fused:
            self._learn_fused(data)
            return
        try:
            self.pipeline.learn_one(data)
        except GraphExecutionError as error:
            self._rolled_back(error)
        self._diagnose(
            self.diagnostics.readiness, self.pipeline.node_states, self.pipeline
        )

    def _rolled_back(
        self,
        error: GraphExecutionError,
        graph: GraphPipeline | None = None,
        detector_id: str | None = None,
    ) -> NoReturn:
        """Skip an observation a step or the detector failed on, if no state changed.

        A score pass only reads committed state, and a learn pass that fails
        before the detector learns rolls every learner back. Both leave the run
        healthy. Uncertain state, from a detector failing while it learned, still
        fails the run.
        """
        graph = graph or self.pipeline
        if isinstance(error, GraphStateUncertainError) or graph.failed:
            raise error
        self._skip(self._failure_node(error, detector_id), "error", str(error))

    def _scores(self, data: dict[str, float]) -> list[float]:
        """Every detector's score; one that fails skips the observation for all."""
        self._diagnose(self.diagnostics.select_pass, "score")
        self.diagnostics.record(self.plan.source_id, self._bound, self._bound)
        scores = []
        for identifier, graph in zip(
            self.plan.detector_ids, self.pipelines, strict=True
        ):
            try:
                score = float(graph.score_one(data))
            except GraphExecutionError as error:
                self._rolled_back(error, graph, identifier)
            if not math.isfinite(score):
                raise ValueError(
                    f"Aberrant returned a non-finite anomaly score for {identifier}"
                )
            scores.append(score)
        return scores

    def _learn_fused(self, data: dict[str, float]) -> None:
        """Every detector learns the observation, after every one has scored it.

        A failure before any detector learned skips the observation, as with one
        detector. A detector that fails afterwards, with its graph rolled back,
        misses only this observation and counts a skip.
        """
        learned = False
        for identifier, graph in zip(
            self.plan.detector_ids, self.pipelines, strict=True
        ):
            try:
                graph.learn_one(data)
            except GraphExecutionError as error:
                if not learned:
                    self._rolled_back(error, graph, identifier)
                if isinstance(error, GraphStateUncertainError) or graph.failed:
                    raise error
                self._diagnose(
                    self.diagnostics.rejected,
                    self._failure_node(error, identifier),
                    None,
                    "error",
                    str(error),
                )
                continue
            learned = True
            self._diagnose(
                self.diagnostics.readiness,
                graph.node_states,
                graph,
                identifier,
                self.plan.owned(identifier),
            )

    def _calibrate_fused(
        self,
        data: dict[str, float],
        topic: str | None,
        charger_id: str | None,
        started: float,
    ) -> AnomalyResult:
        """Keep every detector's score; the combined threshold needs them all."""
        scores = self._scores(data)
        self._learn(data)
        self.calibration_scores.append(scores)
        self.calibration_count += 1
        self.processed_count += 1
        self._detector_results = [
            {"detector_id": identifier, "score": score, "surprise": None}
            for identifier, score in zip(self.plan.detector_ids, scores, strict=True)
        ]
        if self.calibration_count >= self.adaptive_config.calibration_window_size:
            self._freeze_fusion()
            self.state = AdaptiveStreamState.OPERATIONAL
            self._log_calibrated()
        return self._result(data, 0.0, False, "calibration", topic, charger_id, started)

    def _log_calibrated(self) -> None:
        self.logger.info(
            "event=radar.adaptive_calibration_complete threshold=%s "
            "calibration_count=%s processed_count=%s",
            self.threshold,
            self.calibration_count,
            self.processed_count,
        )

    def _freeze_fusion(self) -> None:
        """The threshold: the policy's quantile of the calibration observations'
        combined surprises, each against the other calibration scores."""
        self.fusion = RankFusion(self.calibration_scores, self.plan.fusion)
        self.threshold_count = threshold_count(
            self.fusion, self.adaptive_config.threshold_config.quantile
        )
        self.threshold = self.fusion.value(self.threshold_count)
        values = [self.fusion.value(item) for item in self.fusion.calibration_counts()]
        self.severity_scale = max(abs(self.threshold), max(values) - min(values))

    def _score_fused(self, data: dict[str, float]) -> tuple[float, bool]:
        """The combined surprise, and whether it is above the frozen threshold."""
        if self.fusion is None or self.threshold_count is None:
            raise RuntimeError("Combined detector threshold is not initialized")
        scores = self._scores(data)
        counts = self.fusion.counts(scores)
        combined = int(self.fusion.combined(counts))
        self._detector_results = [
            {
                "detector_id": identifier,
                "score": score,
                "surprise": int(count) / self.fusion.size,
            }
            for identifier, score, count in zip(
                self.plan.detector_ids, scores, counts, strict=True
            )
        ]
        self._diagnose(self.diagnostics.detectors, self._detector_results)
        return self.fusion.value(combined), combined > self.threshold_count

    def _observer(self, detector_id: str):
        """Events of one detector's graph, without the copies of shared steps."""
        owned = self.plan.owned(detector_id)

        def observe(event):
            if event.node_id == "$model":
                if event.phase == "score":
                    self._scored_features = {
                        **(self._scored_features or {}),
                        detector_id: dict(event.inputs),
                    }
                self.diagnostics.observe(event, detector_id)
            elif event.node_id in owned:
                self.diagnostics.observe(event)

        return observe

    def _report_readiness(self) -> None:
        if not self.plan.fused:
            self._diagnose(
                self.diagnostics.readiness, self.pipeline.node_states, self.pipeline
            )
            return
        for identifier, graph in zip(
            self.plan.detector_ids, self.pipelines, strict=True
        ):
            self._diagnose(
                self.diagnostics.readiness,
                graph.node_states,
                graph,
                identifier,
                self.plan.owned(identifier),
            )

    def _observe(self, event):
        if event.node_id == "$model" and event.phase == "score":
            self._scored_features = dict(event.inputs)
        self.diagnostics.observe(event)

    def _record_result(self, result):
        if inference_key(result.context) != "adaptive_stream":
            return
        self._diagnose(self.diagnostics.select_pass, "score")
        self.diagnostics.record(
            self.plan.policy_id,
            {"score": result.anomaly_score},
            float(result.is_anomaly),
        )
        self.diagnostics.record(
            self.plan.output_id,
            {"alarm": float(result.is_anomaly)},
            result.anomaly_score,
        )

    def _pipeline_failed(self) -> bool:
        return any(graph.failed for graph in self.pipelines)

    def _result(
        self,
        data: dict[str, float],
        score: float,
        is_anomaly: bool,
        phase: str,
        topic: str | None,
        charger_id: str | None,
        started: float,
    ) -> AnomalyResult:
        elapsed = time.time() - started
        self.processing_times.append(elapsed)
        threshold = self.threshold
        severity = "low"
        if is_anomaly:
            severity = (
                "high"
                if threshold is not None
                and self.severity_scale > 0
                and score - threshold >= self.severity_scale * 0.5
                else "medium"
            )
        return AnomalyResult(
            anomaly_score=score,
            is_anomaly=is_anomaly,
            severity=severity,
            timestamp=datetime.now(UTC),
            model_info=self.get_model_info(),
            raw_data=data,
            processed_features=None,
            topic=topic,
            charger_id=charger_id,
            context={
                "processing_time_ms": elapsed * 1000,
                "model_type": self.adaptive_config.model_type,
                "adaptive_stream": {
                    "phase": phase,
                    "state": self.state.value,
                    "training_window_size": self.adaptive_config.training_window_size,
                    "calibration_window_size": (
                        self.adaptive_config.calibration_window_size
                    ),
                    "warmup_count": self.warmup_count,
                    "calibration_count": self.calibration_count,
                    "sequence_number": self.operational_count,
                    "anomaly_score": score,
                    "threshold": threshold,
                    "alarm_fired": is_anomaly,
                    "feature_keys": list(self.feature_keys),
                    # Each detector's score and surprise, so an alarm names
                    # the detector that drove it.
                    **(
                        {"detectors": self._detector_results}
                        if self.plan.fused and self._detector_results is not None
                        else {}
                    ),
                },
            },
        )

    def export_checkpoint(self) -> dict[str, Any]:
        """Export state without I/O for the managed persistence barrier."""
        self._require_exportable()
        graphs = (
            {
                "pipelines": self.pipelines,
                "detector_configs": [
                    item.config.as_dict() for item in self._resolved_detectors
                ],
                "detector_fingerprints": [
                    item.fingerprint for item in self._resolved_detectors
                ],
            }
            if self.plan.fused
            else {"pipeline": self.pipeline}
        )
        return self._export_prepare(
            {
                "strategy": "adaptive_stream",
                "adaptive_state": self.state.value,
                "feature_keys": self.feature_keys,
                **graphs,
                "detector_config": self.detector_config.as_dict(),
                "detector_fingerprint": self.detector_fingerprint,
                "severity_scale": self.severity_scale,
                "calibration_scores": self.calibration_scores,
                "threshold": self.threshold,
                "processed_count": self.processed_count,
                "warmup_count": self.warmup_count,
                "calibration_count": self.calibration_count,
                "operational_count": self.operational_count,
                "anomaly_count": self.anomaly_count,
                "training_error": self.training_error,
                "schema_signature": self.schema_signature,
                "aberrant_version": aberrant_version,
            }
        )

    def refresh_background_state(self) -> None:
        """Adaptive models train inline and have no background state."""

    def get_pipeline_state(self) -> dict[str, Any]:
        snapshot = self.diagnostics.snapshot()
        # With several detectors, the slowest one says how far learning is.
        waiting = next(
            (graph for graph in self.pipelines if not graph.readiness.ready),
            self.pipeline,
        )
        snapshot["adaptive_learning"] = {
            "state": self.state.value,
            "model_updates": min(graph.model_updates for graph in self.pipelines),
            "warmup_updates": self.warmup_count,
            "warmup_required": self.adaptive_config.training_window_size,
            "ready": waiting.readiness.ready,
            "reason": waiting.readiness.reason,
        }
        snapshot.update(self._preparation())
        return snapshot

    def get_model_info(self) -> dict[str, Any]:
        return {
            "strategy": "adaptive_stream",
            "state": self.state.value,
            "model_type": self.adaptive_config.model_type,
            **self._fused_info(),
            "catalog_id": self.detector_config.model.id,
            "aberrant_version": aberrant_version,
            "detector_fingerprint": self.detector_fingerprint,
            "capabilities": self.model_capabilities,
            "processed_count": self.processed_count,
            "warmup_count": self.warmup_count,
            "calibration_count": self.calibration_count,
            "operational_count": self.operational_count,
            "anomaly_count": self.anomaly_count,
            "training_window_size": self.adaptive_config.training_window_size,
            "calibration_window_size": self.adaptive_config.calibration_window_size,
            "threshold": self.threshold,
            "training_error": self.training_error,
            **self._preparation(),
            "memory_usage_mb": process_rss_mb(),
            "avg_processing_time_ms": (
                sum(self.processing_times) / max(len(self.processing_times), 1) * 1000
            ),
            "uptime_seconds": time.time() - self.start_time,
        }

    def shutdown(self) -> None:
        """Adaptive models hold no background resources."""
