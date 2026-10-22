"""Readiness-aware feature graphs using the existing adaptive alarm lifecycle."""

from __future__ import annotations

import hashlib
import math
from typing import Any

from aberrant.compose import GraphPipeline
from off_key_core.models.pipelines import execution_fingerprint

from ..adaptive_detector import AdaptiveStreamDetectionService, AdaptiveStreamState
from ..execution_errors import FatalExecutionError, ObservationRejected
from ..models import inference_key
from .adapters import adaptive_graph, detector_config
from .diagnostics import PipelineDiagnostics
from .plan import ExecutionPlan


class AdaptivePipelineDetectionService(AdaptiveStreamDetectionService):
    """Warm transforms without contaminating downstream models or calibration."""

    def __init__(self, config, checkpoint=None):
        if config.pipeline is None:
            raise ValueError("A bound pipeline configuration is required")
        self.plan = ExecutionPlan(config.pipeline)
        if self.plan.execution.definition.strategy != "adaptive_stream":
            raise ValueError("Adaptive execution requires an adaptive pipeline")
        if config.pipeline.fingerprint != execution_fingerprint(
            config.pipeline.definition, config.pipeline.bindings
        ):
            raise ValueError("Pipeline execution fingerprint does not match its design")
        self.diagnostics = PipelineDiagnostics(config.pipeline)
        self._execution_failed = False
        self._scored_features: dict[str, float] | None = None
        super().__init__(config, checkpoint)
        self._raw_unit_interval_slots = self._unit_interval_slots()
        self._diagnose(
            self.diagnostics.readiness, self.pipeline.node_states, self.pipeline
        )

    @staticmethod
    def _build_schema_signature(config):
        legacy = AdaptiveStreamDetectionService._build_schema_signature(config)
        return hashlib.sha256(
            f"{legacy}:{config.pipeline.fingerprint}".encode()
        ).hexdigest()

    def _detector_config(self, feature_keys=None):
        return detector_config(self.plan)

    def _build_pipeline(self, config):
        return adaptive_graph(self.plan, self._observe)[0]

    def _restore(self, checkpoint):
        if checkpoint.get("schema_signature") != self.schema_signature:
            raise ValueError("Adaptive graph checkpoint configuration is incompatible")
        super()._restore(checkpoint)
        if not isinstance(self.pipeline, GraphPipeline) or self.pipeline.failed:
            raise ValueError("Checkpoint has no usable adaptive graph")
        if self.state == AdaptiveStreamState.FAILED:
            raise ValueError("Failed adaptive executions cannot be restored")
        self.pipeline.observer = self._observe

    def process_data_point(self, data, topic=None, charger_id=None):
        if self._execution_failed or self.pipeline.failed:
            raise FatalExecutionError(
                self.training_error or "Pipeline execution has failed"
            )
        bound = self._validated_observation(data)
        self._scored_features = None
        self._diagnose(
            self.diagnostics.begin, self.processed_count + 1, self.state.value
        )
        try:
            result = super().process_data_point(bound, topic, charger_id)
            result.raw_data = dict(data)
            result.processed_features = self._scored_features
            self._record_result(result)
            return result
        except Exception as error:
            self._execution_failed = True
            self.state = AdaptiveStreamState.FAILED
            self.training_error = str(error)
            identifier = getattr(error, "node_id", self.plan.compiled.detector_id)
            if identifier == "$model":
                identifier = self.plan.compiled.detector_id
            self._diagnose(self.diagnostics.fail, identifier, error)
            raise FatalExecutionError(str(error)) from error
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
        if not self.detector_config.capabilities().requires_unit_interval:
            return frozenset()
        return frozenset(
            slot
            for feature in self.plan.compiled.features[
                self.plan.compiled.feature_output_id
            ]
            if feature.raw
            for slot in feature.slots
        )

    def _process_warmup(self, data, topic, charger_id, started):
        self._learn(data)
        self.warmup_count = self.pipeline.last_learning_outcome.model_updates
        self.processed_count += 1
        if (
            self.warmup_count >= self.adaptive_config.training_window_size
            and self.pipeline.readiness.ready
        ):
            self.state = AdaptiveStreamState.CALIBRATING
        return self._result(data, 0.0, False, "warmup", topic, charger_id, started)

    def _score(self, data):
        self._diagnose(self.diagnostics.select_pass, "score")
        self._diagnose(
            self.diagnostics.record, self.plan.compiled.source_id, data, data
        )
        return super()._score(data)

    def _learn(self, data):
        self._diagnose(self.diagnostics.select_pass, "learn")
        self._diagnose(
            self.diagnostics.record, self.plan.compiled.source_id, data, data
        )
        super()._learn(data)
        self._diagnose(
            self.diagnostics.readiness, self.pipeline.node_states, self.pipeline
        )

    def _observe(self, event):
        if event.node_id == "$model" and event.phase == "score":
            self._scored_features = dict(event.inputs)
        self.diagnostics.observe(event)

    def _record_result(self, result):
        if inference_key(result.context) != "adaptive_stream":
            return
        self._diagnose(self.diagnostics.select_pass, "score")
        self._diagnose(
            self.diagnostics.record,
            self.plan.compiled.policy_id,
            {"score": result.anomaly_score},
            float(result.is_anomaly),
        )
        self._diagnose(
            self.diagnostics.record,
            self.plan.compiled.output_id,
            {"alarm": float(result.is_anomaly)},
            result.anomaly_score,
        )

    def _diagnose(self, operation, *args):
        try:
            operation(*args)
        except Exception:
            self.diagnostics.errors += 1

    def export_checkpoint(self):
        if self._execution_failed or self.pipeline.failed:
            raise FatalExecutionError("Failed pipeline state cannot be checkpointed")
        return super().export_checkpoint()

    def get_pipeline_state(self) -> dict[str, Any]:
        snapshot = self.diagnostics.snapshot()
        snapshot["adaptive_learning"] = {
            "state": self.state.value,
            "model_updates": self.pipeline.model_updates,
            "warmup_updates": self.warmup_count,
            "warmup_required": self.adaptive_config.training_window_size,
            "ready": self.pipeline.readiness.ready,
            "reason": self.pipeline.readiness.reason,
        }
        return snapshot

    def attach_observation_metadata(self, timestamp, input_timestamps):
        self._diagnose(
            self.diagnostics.metadata,
            self.processed_count,
            timestamp,
            input_timestamps,
        )
