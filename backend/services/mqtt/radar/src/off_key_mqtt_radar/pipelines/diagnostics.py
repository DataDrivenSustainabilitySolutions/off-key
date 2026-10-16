"""Bounded diagnostics from one real observation, without additional inference."""

from __future__ import annotations

import json
import math
import time
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DiagnosticLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sample_interval_seconds: float = Field(default=1.0, gt=0)
    preview_features: int = Field(default=8, ge=1, le=100)
    maximum_bytes: int = Field(default=128 * 1024, ge=4096, le=1024 * 1024)
    maximum_error_bytes: int = Field(default=256, ge=16, le=256)


class PipelineDiagnostics:
    """Owned by the serial model thread; readers receive detached snapshots."""

    def __init__(self, execution, limits: DiagnosticLimits | None = None):
        self.limits = limits or DiagnosticLimits()
        self.run_id = execution.run_id
        self.revision_id = execution.revision_id
        self.fingerprint = execution.fingerprint
        self.model_id = next(
            node.id for node in execution.definition.nodes if node.kind == "detector"
        )
        self.source_id = next(
            node.id for node in execution.definition.nodes if node.kind == "source"
        )
        self.model_input = next(
            edge.source
            for edge in execution.definition.edges
            if edge.target == self.model_id
        )
        self.nodes = {
            node.id: dict(
                state="waiting",
                learn_count=0,
                score_count=0,
                learn_time_ns=0,
                score_time_ns=0,
                ready=False,
                learned_updates=None,
                readiness_observed=None,
                readiness_required=None,
                readiness_reason=None,
                blocked_by=[],
            )
            for node in execution.definition.nodes
        }
        self.phase = "waiting_for_data"
        self.sequence_number = 0
        self.errors = 0
        self._last_sample = float("-inf")
        self._pending: dict[str, Any] | None = None
        self._observation: dict[str, Any] | None = None
        self._pass = "learn"
        self._captured_at = datetime.now(UTC).isoformat()

    @property
    def sampling(self) -> bool:
        return self._pending is not None

    def begin(self, sequence: int, phase: str) -> None:
        self.sequence_number = sequence
        self.phase = phase
        now = time.monotonic()
        self._pending = None
        if now - self._last_sample >= self.limits.sample_interval_seconds:
            self._last_sample = now
            self._pending = {
                "sequence_number": sequence,
                "timestamp": datetime.now(UTC).isoformat(),
                "phase": phase,
                "input_timestamps": {},
                "passes": {"score": {}, "learn": {}},
            }

    def select_pass(self, phase: str) -> None:
        if phase not in {"score", "learn"}:
            raise ValueError("Diagnostics pass must be score or learn")
        self._pass = phase

    def observe(self, event) -> None:
        """Consume an Aberrant NodeObservation without retaining its full data."""
        identifier = self.model_id if event.node_id == "$model" else event.node_id
        output = dict(event.output) if isinstance(event.output, tuple) else event.output
        self.record(
            identifier,
            dict(event.inputs),
            output,
            elapsed_ns=event.duration_ns,
            count=(event.phase != "transform" or self._pass == "score"),
        )

    def record(
        self,
        node_id: str,
        inputs: dict[str, float] | None,
        output: dict[str, float] | float | None,
        *,
        elapsed_ns: int = 0,
        count: bool = True,
        state: str = "ready",
        reason: str | None = None,
    ) -> None:
        """Diagnostic failures never replace an execution's result or exception."""
        try:
            metrics = self.nodes[node_id]
            metrics["state"] = state
            metrics["ready"] = state == "ready"
            if count:
                metrics[f"{self._pass}_count"] += 1
            metrics[f"{self._pass}_time_ns"] += max(int(elapsed_ns), 0)
            if self._pending is not None:
                preview = {
                    "input": self._preview(inputs),
                    "output": self._preview(output),
                    "state": state,
                }
                if reason is not None:
                    preview["reason"] = self._bounded_text(reason)
                self._pending["passes"][self._pass][node_id] = preview
        except Exception:
            self.errors += 1

    def readiness(self, states, graph=None) -> None:
        for item in states:
            metrics = self.nodes.get(item.node_id)
            if metrics is not None:
                self._readiness(metrics, item.updates, item.readiness, item.blocked_by)
        if graph is not None:
            # Aberrant's node_states covers feature nodes. Its public graph
            # readiness and model_updates describe the terminal learner.
            blocked = (
                (self.model_input,)
                if self.model_input != self.source_id
                and not self.nodes[self.model_input]["ready"]
                else ()
            )
            self._readiness(
                self.nodes[self.model_id], graph.model_updates, graph.readiness, blocked
            )

    def _readiness(self, metrics, updates, readiness, blocked) -> None:
        blockers = list(dict.fromkeys(key for key in blocked if key in self.nodes))
        metrics.update(
            ready=readiness.ready,
            state=(
                "waiting_for_dependency"
                if blockers
                else "ready"
                if readiness.ready
                else "initializing"
            ),
            learned_updates=updates,
            readiness_observed=readiness.observed,
            readiness_required=readiness.required,
            readiness_reason=self._bounded_text(readiness.reason, maximum_bytes=128),
            blocked_by=blockers,
        )

    def fail(self, node_id: str, error: Exception) -> None:
        self.phase = "failed"
        metrics = self.nodes.get(node_id)
        if metrics is not None:
            bounded_error = self._bounded_text(str(error))
            metrics.update(state="failed", ready=False, error=bounded_error)

    def finish(self) -> None:
        self._captured_at = datetime.now(UTC).isoformat()
        if self._pending is None:
            return
        for phase in ("score", "learn"):
            previews = self._pending["passes"][phase]
            for identifier in self.nodes:
                previews.setdefault(
                    identifier,
                    {
                        "input": None,
                        "output": None,
                        "state": "not_executed",
                        "reason": f"Not executed in this observation's {phase} pass",
                    },
                )
        self._observation = self._pending
        self._pending = None

    def metadata(
        self, sequence: int, timestamp: datetime, input_timestamps: dict
    ) -> None:
        if (
            self._observation is None
            or self._observation["sequence_number"] != sequence
        ):
            return
        self._observation["timestamp"] = timestamp.isoformat()
        normalized = {}
        for name, value in input_timestamps.items():
            try:
                normalized[name] = (
                    datetime.fromtimestamp(float(value), UTC).isoformat()
                    if isinstance(value, int | float)
                    else str(value)
                )
            except (ValueError, OverflowError, OSError):
                self.errors += 1
        self._observation["input_timestamps"] = normalized

    def snapshot(self) -> dict[str, Any]:
        snapshot = dict(
            run_id=self.run_id,
            revision_id=self.revision_id,
            fingerprint=self.fingerprint,
            captured_at=self._captured_at,
            phase=self.phase,
            sequence_number=self.sequence_number,
            nodes=deepcopy(self.nodes),
            observation=deepcopy(self._observation),
            truncated=False,
            diagnostic_errors=self.errors,
        )
        if (
            len(json.dumps(snapshot, allow_nan=False).encode())
            > self.limits.maximum_bytes
        ):
            snapshot["observation"] = None
            snapshot["truncated"] = True
        return snapshot

    def _preview(self, value):
        if value is None:
            return None
        if isinstance(value, dict):
            return {
                name: float(item)
                for name, item in list(value.items())[: self.limits.preview_features]
                if math.isfinite(float(item))
            }
        result = float(value)
        return result if math.isfinite(result) else None

    def _bounded_text(
        self, value: str | None, *, maximum_bytes: int = 256
    ) -> str | None:
        if value is None:
            return None
        limit = min(self.limits.maximum_error_bytes, maximum_bytes)
        bounded = value.encode("utf-8", errors="replace")[:limit].decode(
            "utf-8", errors="ignore"
        )
        # JSON escaping can expand a Unicode/control character beyond its UTF-8
        # size. Bound both representations so status-only snapshots remain small.
        if len(json.dumps(bounded)) - 2 <= limit:
            return bounded
        low, high = 0, len(bounded)
        while low < high:
            middle = (low + high + 1) // 2
            if len(json.dumps(bounded[:middle])) - 2 <= limit:
                low = middle
            else:
                high = middle - 1
        return bounded[:low]
