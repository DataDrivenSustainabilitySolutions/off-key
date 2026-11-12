"""Execution members shared by the static and adaptive detectors."""

from __future__ import annotations

import hashlib
from typing import Any, NoReturn

from ..execution_errors import FatalExecutionError, StepRejected
from .diagnostics import PipelineDiagnostics
from .plan import ExecutionPlan
from .prepare import PrepareStage, Withheld


class PipelineExecutionMixin:
    """Plan, diagnostics and failure bookkeeping of one bound pipeline run."""

    plan: ExecutionPlan
    diagnostics: PipelineDiagnostics
    prepare: PrepareStage | None
    _execution_failed: bool
    _alarm_muted: bool

    def _init_pipeline_execution(self, config) -> None:
        self.plan = ExecutionPlan(config.pipeline)
        self.diagnostics = PipelineDiagnostics(config.pipeline)
        self._execution_failed = False
        # The policy fired on the current observation and a Mute alarms step
        # kept the alarm from being raised.
        self._alarm_muted = False
        stage = self.plan.stage
        self.prepare = PrepareStage(self.plan) if stage is not None else None
        if stage is not None:
            self.diagnostics.external = frozenset(stage.frontier)

    def _prepared(
        self, bound: dict[str, float], timestamp: float | None = None
    ) -> dict[str, float] | Withheld:
        """The learned stage's input, or why it gets none from this observation.

        It gets none while the Prepare stage warms up, and none when a Gate
        holds the observation back. A rejected observation raises
        PrepareRejected and changes no state. timestamp is when the
        observation was measured, for the steps that read time.
        """
        self._alarm_muted = False
        if self.prepare is None:
            return bound
        prepared = self.prepare.run(bound, self.diagnostics, timestamp)
        if isinstance(prepared, Withheld) and prepared.reason == "preparing":
            self.diagnostics.phase = "preparing"
        return prepared

    @property
    def _muting(self) -> bool:
        """Whether a Mute alarms step's condition holds on the current observation."""
        return self.prepare is not None and self.prepare.muting

    def _raised(self, fired: bool) -> bool:
        """Whether an alarm the policy fired is raised.

        It is not while a Mute alarms step's condition holds. The policy has
        counted the observation as any other, and the evidence keeps the alarm
        as muted.
        """
        self._alarm_muted = bool(fired) and self._muting
        return bool(fired) and not self._alarm_muted

    def _skip(
        self,
        node_id: str,
        reason: str,
        message: str,
        inputs: dict[str, float] | None = None,
    ) -> NoReturn:
        """Skip an observation that a learned step or the detector could not process.

        Only call this when the learned stage is as it was: Aberrant rolled every
        learner back, or the step only read fitted state. The Prepare stage takes
        the observation back too, so a skipped observation changes no state, and
        the run counts it as a coverage gap.
        """
        if self.prepare is not None:
            self.prepare.revert()
        self._diagnose(self.diagnostics.rejected, node_id, inputs, reason, message)
        raise StepRejected(node_id, reason, message)

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

    def _failure_node(
        self, error: BaseException, detector_id: str | None = None
    ) -> str:
        """Name the failing node; model-level errors belong to the detector."""
        detector_id = detector_id or self.plan.detector_id
        node = getattr(error, "node_id", None) or detector_id
        return detector_id if node == "$model" else node

    def _fused_info(self) -> dict[str, Any]:
        """Which detectors the policy combines, and how; nothing for one."""
        if not self.plan.fused:
            return {}
        return {
            "fusion": self.plan.fusion,
            "detectors": [
                {
                    "detector_id": identifier,
                    "model_type": self.plan.nodes[identifier].component.removeprefix(
                        "detector:"
                    ),
                }
                for identifier in self.plan.detector_ids
            ],
        }

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
