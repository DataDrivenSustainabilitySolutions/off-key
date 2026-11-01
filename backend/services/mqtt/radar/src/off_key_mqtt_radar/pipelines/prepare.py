"""The Prepare stage: one transactional pass per observation, before learning.

Both strategies run it on every observation in arrival order, also while a
static baseline fits in the background, so the learned stage starts on a
continuous history. Its output is the learned stage's input: one column per
feature crossing the cut, named <node>.<feature>.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter_ns
from typing import Any

from off_key_core.models.pipeline_prepare import (
    PREPARE_COMPONENTS,
    Kernel,
    PrepareFailure,
    kernel,
)
from off_key_core.models.pipeline_scope import step_scope

from ..execution_errors import ObservationRejected
from .plan import ExecutionPlan

STATE_VERSION = 1


class PrepareRejected(ObservationRejected):
    """A Prepare step skipped this observation; every state stays as it was."""

    def __init__(self, node_id: str, reason: str, message: str):
        super().__init__(message)
        self.node_id = node_id
        self.reason = reason


@dataclass(frozen=True)
class _Step:
    id: str
    component: str
    parents: tuple[str, ...]
    params: dict[str, Any]
    kernel: Kernel | None = None
    """None for the routes in front of a Prepare step."""
    selected: tuple[str, ...] = ()
    targets: tuple[str, ...] = ()
    """Where each selected feature's value goes: its own name, or an added one."""
    required: int = field(default=0)
    """Inputs before the step's first output."""


class PrepareStage:
    """Run a design's Prepare steps once per observation.

    A pass stages each step's next state. It commits only when every step that
    received input produced finite values; a rejection leaves all state as it
    was. A step still warming up produces no output, and the steps after it wait.
    """

    def __init__(self, plan: ExecutionPlan):
        stage = plan.stage
        if stage is None:
            raise ValueError("The design has no Prepare stage")
        self.source_id = plan.source_id
        self.frontier = stage.frontier
        self.required = stage.required
        self.names = {
            identifier: tuple(plan.names(identifier))
            for identifier in (*stage.steps, plan.source_id)
        }
        self.steps = [
            self._step(plan, plan.nodes[identifier]) for identifier in stage.steps
        ]
        self.states: dict[str, list[tuple]] = {
            step.id: [step.kernel.initial() for _ in step.selected]
            for step in self.steps
            if step.kernel is not None
        }
        self.updates = {step.id: 0 for step in self.steps}
        self.accepted = 0
        self.rejected = 0

    @staticmethod
    def _step(plan: ExecutionPlan, node) -> _Step:
        parents = tuple(plan.parents(node.id))
        if node.component not in PREPARE_COMPONENTS:
            return _Step(node.id, node.component, parents, dict(node.params))
        step = kernel(node.component, node.params)
        scope = step_scope(node.component, node.params, plan.names(parents[0]))
        return _Step(
            node.id,
            node.component,
            parents,
            dict(node.params),
            step,
            scope.selected,
            scope.added if scope.add else scope.selected,
            step.lead + 1,
        )

    @property
    def ready(self) -> bool:
        return self.accepted >= self.required

    def status(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "observed": min(self.accepted, self.required),
            "required": self.required,
            "rejected": self.rejected,
        }

    def run(self, bound: dict[str, float], diagnostics=None) -> dict[str, float] | None:
        """Prepare one observation: its learned-stage input, or None while warming up.

        Raises PrepareRejected when a step cannot produce a finite value.
        """
        available: dict[str, dict[str, float]] = {self.source_id: bound}
        staged: dict[str, list[tuple]] = {}
        records = []
        for step in self.steps:
            started = perf_counter_ns()
            blocked = tuple(key for key in step.parents if key not in available)
            if blocked:
                records.append((step, None, None, 0, blocked))
                continue
            values = available[step.parents[0]]
            if step.kernel is None:
                output = self._route(step, available)
            else:
                output = self._advance(step, values, staged, diagnostics)
            if output is not None:
                available[step.id] = output
            # A merge's inputs are its branches; its output shows them in order.
            shown = output if step.component == "features.merge" else values
            records.append((step, shown, output, perf_counter_ns() - started, ()))
        self.states.update(staged)
        self.accepted += 1
        for step, values, _output, _elapsed, _blocked in records:
            if values is not None:
                self.updates[step.id] += 1
        if diagnostics is not None:
            self._report(diagnostics, records)
        if any(key not in available for key in self.frontier):
            return None
        return {
            f"{key}.{name}": available[key][name]
            for key in self.frontier
            for name in self.names[key]
        }

    def _advance(self, step: _Step, values, staged, diagnostics):
        assert step.kernel is not None
        states = self.states[step.id]
        advanced = []
        outputs: dict[str, float] = {}
        complete = True
        for index, name in enumerate(step.selected):
            try:
                state, value = step.kernel.advance(states[index], values[name])
            except PrepareFailure as failure:
                self.rejected += 1
                message = f"{name}: {failure}"
                if diagnostics is not None:
                    _safely(
                        diagnostics,
                        diagnostics.prepare_rejected,
                        step.id,
                        values,
                        failure.reason,
                        message,
                    )
                raise PrepareRejected(step.id, failure.reason, message) from failure
            advanced.append(state)
            if value is None:
                complete = False
            else:
                outputs[step.targets[index]] = value
        staged[step.id] = advanced
        # Every feature of a step warms up on the same observations.
        return {**values, **outputs} if complete else None

    @staticmethod
    def _route(step: _Step, available) -> dict[str, float]:
        values = available[step.parents[0]]
        if step.component == "features.select":
            return {name: values[name] for name in step.params["features"]}
        if step.component == "features.rename":
            mapping = step.params["mapping"]
            return {mapping.get(name, name): value for name, value in values.items()}
        if step.component == "features.merge":
            return {
                name: value
                for parent in step.parents
                for name, value in available[parent].items()
            }
        return dict(values)

    def _report(self, diagnostics, records) -> None:
        for step, values, output, elapsed, blocked in records:
            _safely(
                diagnostics,
                diagnostics.prepare_step,
                step.id,
                values,
                output,
                elapsed_ns=elapsed,
                updates=self.updates[step.id] if step.kernel is not None else None,
                required=step.required or None,
                blocked_by=blocked,
            )

    def export_state(self) -> dict[str, Any]:
        """Plain data for checkpoints; states are never changed in place."""
        return {
            "version": STATE_VERSION,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "updates": dict(self.updates),
            "states": {key: list(value) for key, value in self.states.items()},
        }

    def load_state(self, state: dict[str, Any]) -> None:
        """Continue a checkpointed history; a state of another design is refused."""
        if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
            raise ValueError("Prepare checkpoint has an unknown format")
        states = state.get("states")
        updates = state.get("updates")
        if (
            not isinstance(states, dict)
            or set(states) != set(self.states)
            or not isinstance(updates, dict)
            or set(updates) != set(self.updates)
        ):
            raise ValueError("Prepare checkpoint does not match this design")
        for step in self.steps:
            if step.kernel is None:
                continue
            lanes = states[step.id]
            if (
                not isinstance(lanes, list | tuple)
                or len(lanes) != len(step.selected)
                or not all(
                    isinstance(lane, tuple) and step.kernel.accepts(lane)
                    for lane in lanes
                )
            ):
                raise ValueError(f"Prepare checkpoint state of {step.id} is invalid")
        counts = [state.get("accepted"), state.get("rejected"), *updates.values()]
        if not all(isinstance(value, int) and value >= 0 for value in counts):
            raise ValueError("Prepare checkpoint counts are invalid")
        self.states = {key: list(value) for key, value in states.items()}
        self.updates = dict(updates)
        self.accepted = state["accepted"]
        self.rejected = state["rejected"]


def _safely(diagnostics, operation, *args, **kwargs) -> None:
    """Diagnostics never replace an execution's result or exception."""
    try:
        operation(*args, **kwargs)
    except Exception:
        diagnostics.errors += 1


__all__ = ["PrepareRejected", "PrepareStage"]
