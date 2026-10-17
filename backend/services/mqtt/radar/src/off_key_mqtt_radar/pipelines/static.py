"""Static graph runs using the existing conformal and martingale lifecycle."""

from __future__ import annotations

import hashlib
import math
from time import perf_counter_ns

import numpy as np

from ..detector import StaticConformalDetectionService, StaticConformalState
from ..execution_errors import FatalExecutionError, ObservationRejected
from .batch import BatchFeatureGraph, FittedStaticPipeline
from .diagnostics import PipelineDiagnostics
from .plan import ExecutionPlan


class StaticPipelineDetectionService(StaticConformalDetectionService):
    """Publish an independently fitted, frozen graph atomically with its model."""

    def __init__(self, config, checkpoint=None, *, automatic_checkpoints=True):
        if config.pipeline is None:
            raise ValueError("A bound pipeline configuration is required")
        self.plan = ExecutionPlan(config.pipeline)
        self.diagnostics = PipelineDiagnostics(config.pipeline)
        self._execution_failed = False
        super().__init__(
            config, checkpoint, automatic_checkpoints=automatic_checkpoints
        )

    @staticmethod
    def _build_schema_signature_from_config(config):
        legacy = StaticConformalDetectionService._build_schema_signature_from_config(
            config
        )
        return hashlib.sha256(
            f"{legacy}:{config.pipeline.fingerprint}".encode()
        ).hexdigest()

    def _vectorize(self, data):
        return [data[name] for name in self.plan.names(self.plan.compiled.source_id)]

    def _fit_static_baseline(self, training_samples, calibration_samples, feature_keys):
        graph = BatchFeatureGraph(self.plan)
        names = self.plan.names(self.plan.compiled.source_id)
        training = graph.fit_transform(
            np.asarray([[row[key] for key in names] for row in training_samples])
        )
        calibration = graph.transform(
            np.asarray([[row[key] for key in names] for row in calibration_samples])
        )
        fitted, policy = self._fit_static_matrices(training, calibration)
        return FittedStaticPipeline(graph, fitted), policy

    def process_data_point(self, data, topic=None, charger_id=None):
        if self._execution_failed:
            raise FatalExecutionError(
                self.training_error or "Pipeline execution has failed"
            )
        try:
            bound = self.plan.bind(data)
            if not all(math.isfinite(value) for value in bound.values()):
                raise ObservationRejected("Pipeline inputs must be finite")
        except (TypeError, ValueError, OverflowError) as error:
            raise ObservationRejected(str(error)) from error
        self._diagnose(
            self.diagnostics.begin, self.processed_count + 1, self.state.value
        )
        self._diagnose(
            self.diagnostics.select_pass,
            "score" if self.state == StaticConformalState.READY else "learn",
        )
        self._diagnose(
            self.diagnostics.record, self.plan.compiled.source_id, bound, bound
        )
        try:
            result = super().process_data_point(bound, topic, charger_id)
            result.raw_data = dict(data)
            if result.should_persist:
                result.processed_features = self.conformal_detector.last_features
                self._diagnose(
                    self.diagnostics.record,
                    self.plan.compiled.output_id,
                    None,
                    result.anomaly_score,
                )
            return result
        except Exception as error:
            self._execution_failed = True
            self.state = StaticConformalState.FAILED
            self.training_error = str(error)
            identifier = (
                getattr(error, "node_id", None) or self.plan.compiled.detector_id
            )
            self._diagnose(self.diagnostics.fail, identifier, error)
            raise FatalExecutionError(str(error), node_id=identifier) from error
        finally:
            self._diagnose(self.diagnostics.finish)

    def _process_ready(self, *args, **kwargs):
        self._diagnose(self.diagnostics.select_pass, "score")
        self.conformal_detector.observer = self.diagnostics
        return super()._process_ready(*args, **kwargs)

    def _update_alarm_policy(self, p_value):
        started = perf_counter_ns()
        try:
            context = super()._update_alarm_policy(p_value)
        except Exception as error:
            raise FatalExecutionError(
                str(error), node_id=self.plan.compiled.policy_id
            ) from error
        self._diagnose(
            self.diagnostics.record,
            self.plan.compiled.policy_id,
            {"p_value": p_value},
            float(context["alarm_fired"]),
            elapsed_ns=perf_counter_ns() - started,
        )
        return context

    def _complete_training_if_ready(self):
        previous = self.state
        fitting_error = (
            self._training_future.exception()
            if self._training_future is not None and self._training_future.done()
            else None
        )
        super()._complete_training_if_ready()
        if (
            previous != StaticConformalState.READY
            and self.state == StaticConformalState.READY
        ):
            self._diagnose(self._publish_fit_readiness)
        if self.state == StaticConformalState.FAILED:
            self._execution_failed = True
            error = FatalExecutionError(
                self.training_error or "Static pipeline fitting failed",
                node_id=getattr(fitting_error, "node_id", None)
                or self.plan.compiled.detector_id,
            )
            self._diagnose(self.diagnostics.fail, error.node_id, error)
            raise error

    def _publish_fit_readiness(self):
        for node in self.plan.feature_nodes:
            self.diagnostics.nodes[node.id].update(state="ready", ready=True)
        self.diagnostics.nodes[self.plan.compiled.detector_id].update(
            state="ready", ready=True
        )

    def export_checkpoint(self):
        if self._execution_failed:
            raise FatalExecutionError("Failed pipeline state cannot be checkpointed")
        return super().export_checkpoint()

    def get_pipeline_state(self):
        state = self.diagnostics.snapshot()
        state["phase"] = self.state.value
        state["batch_training"] = {
            "state": self.state.value,
            "training_samples": len(self.training_buffer),
            "calibration_samples": len(self.calibration_buffer),
            "frozen": self.state == StaticConformalState.READY,
        }
        return state

    def attach_observation_metadata(self, timestamp, input_timestamps):
        self._diagnose(
            self.diagnostics.metadata, self.processed_count, timestamp, input_timestamps
        )

    def _diagnose(self, operation, *args, **kwargs):
        try:
            operation(*args, **kwargs)
        except Exception:
            self.diagnostics.errors += 1
