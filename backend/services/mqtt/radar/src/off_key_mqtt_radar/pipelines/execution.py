"""Execution members shared by the static and adaptive detectors."""

from __future__ import annotations

import hashlib
from typing import Any

from ..execution_errors import FatalExecutionError
from .diagnostics import PipelineDiagnostics
from .plan import ExecutionPlan
from .prepare import PrepareStage, Withheld


class PipelineExecutionMixin:
    """Plan, diagnostics and failure bookkeeping of one bound pipeline run."""

    plan: ExecutionPlan
    diagnostics: PipelineDiagnostics
    prepare: PrepareStage | None
    _execution_failed: bool

    def _init_pipeline_execution(self, config) -> None:
        self.plan = ExecutionPlan(config.pipeline)
        self.diagnostics = PipelineDiagnostics(config.pipeline)
        self._execution_failed = False
        stage = self.plan.stage
        self.prepare = PrepareStage(self.plan) if stage is not None else None
        if stage is not None:
            self.diagnostics.external = frozenset(stage.frontier)

    def _prepared(self, bound: dict[str, float]) -> dict[str, float] | Withheld:
        """The learned stage's input, or why it gets none from this observation.

        It gets none while the Prepare stage warms up, and none when a Gate
        holds the observation back. A rejected observation raises
        PrepareRejected and changes no state.
        """
        if self.prepare is None:
            return bound
        prepared = self.prepare.run(bound, self.diagnostics)
        if isinstance(prepared, Withheld) and prepared.reason == "preparing":
            self.diagnostics.phase = "preparing"
        return prepared

    def _preparation(self) -> dict[str, Any]:
        return {} if self.prepare is None else {"preparation": self.prepare.status()}

    def _export_prepare(self, checkpoint: dict[str, Any]) -> dict[str, Any]:
        if self.prepare is not None:
            checkpoint["prepare"] = self.prepare.export_state()
        return checkpoint

    def _restore_prepare(self, checkpoint: dict[str, Any]) -> None:
        if self.prepare is None:
            return
        state = checkpoint.get("prepare")
        if state is None:
            raise ValueError("Checkpoint is missing its Prepare stage state")
        self.prepare.load_state(state)

    @staticmethod
    def _pipeline_signature(settings: str, config) -> str:
        return hashlib.sha256(
            f"{settings}:{config.pipeline.fingerprint}".encode()
        ).hexdigest()

    def _failure_node(self, error: BaseException) -> str:
        """Name the failing node; model-level errors belong to the detector."""
        detector_id = self.plan.detector_id
        node = getattr(error, "node_id", None) or detector_id
        return detector_id if node == "$model" else node

    def _pipeline_failed(self) -> bool:
        return False

    def _require_exportable(self) -> None:
        if self._execution_failed or self._pipeline_failed():
            raise FatalExecutionError("Failed pipeline state cannot be checkpointed")

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
