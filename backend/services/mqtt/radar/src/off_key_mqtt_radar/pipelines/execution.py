"""Execution members shared by the static and adaptive pipeline wrappers."""

from __future__ import annotations

import hashlib

from ..execution_errors import FatalExecutionError
from .diagnostics import PipelineDiagnostics
from .plan import ExecutionPlan


class PipelineExecutionMixin:
    """Listed before the legacy detector base so its overrides win."""

    plan: ExecutionPlan
    diagnostics: PipelineDiagnostics
    _execution_failed: bool

    def _init_pipeline_execution(self, config) -> None:
        if config.pipeline is None:
            raise ValueError("A bound pipeline configuration is required")
        self.plan = ExecutionPlan(config.pipeline)
        self.diagnostics = PipelineDiagnostics(config.pipeline)
        self._execution_failed = False

    @staticmethod
    def _pipeline_signature(legacy: str, config) -> str:
        return hashlib.sha256(
            f"{legacy}:{config.pipeline.fingerprint}".encode()
        ).hexdigest()

    def _failure_node(self, error: BaseException) -> str:
        """Name the failing node; model-level errors belong to the detector."""
        detector_id = self.plan.compiled.detector_id
        node = getattr(error, "node_id", None) or detector_id
        return detector_id if node == "$model" else node

    def _pipeline_failed(self) -> bool:
        return False

    def _require_exportable(self) -> None:
        if self._execution_failed or self._pipeline_failed():
            raise FatalExecutionError("Failed pipeline state cannot be checkpointed")

    def export_checkpoint(self):
        self._require_exportable()
        return super().export_checkpoint()

    def attach_observation_metadata(self, timestamp, input_timestamps):
        self._diagnose(
            self.diagnostics.metadata,
            self.processed_count,
            timestamp,
            input_timestamps,
        )

    def _diagnose(self, operation, *args, **kwargs):
        """Diagnostics never replace an execution's result or exception."""
        try:
            operation(*args, **kwargs)
        except Exception:
            self.diagnostics.errors += 1
