"""The Prepare stage: one transactional pass per observation, before learning.

Both strategies run it on every observation in arrival order, also while a
static baseline fits in the background, so the learned stage starts on a
continuous history. Its output is the learned stage's input: one column per
feature crossing the cut, named <node>.<feature>. A Gate whose condition fails
withholds the observation: the steps before it keep what they saw, the steps
after it see nothing, and nothing learns or scores.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from time import perf_counter_ns
from typing import Any

from off_key_core.models.pipeline_combine import (
    Gate,
    RowStep,
    lane_context,
    row_step,
)
from off_key_core.models.pipeline_prepare import (
    LANE_COMPONENTS,
    ROW_COMPONENTS,
    Kernel,
    PrepareFailure,
    kernel,
)
from off_key_core.models.pipeline_scope import step_scope

from ..execution_errors import StepRejected
from .plan import ExecutionPlan

STATE_VERSION = 1


class PrepareRejected(StepRejected):
    """A Prepare step skipped this observation; every state stays as it was."""


@dataclass(frozen=True)
class Withheld:
    """An observation the learned stage does not see, and why."""

    reason: str
    """preparing while windows fill, or held_back when a Gate's condition fails."""
    node_id: str | None = None
    """The Gate that held it back."""


@dataclass(frozen=True)
class _Step:
    id: str
    component: str
    parents: tuple[str, ...]
    params: dict[str, Any]
    kernel: Kernel | None = None
    """The per-feature step; None for row steps and routes."""
    row: RowStep | None = None
    """Aggregate, Formula or Gate, which work on the whole row."""
    context: Callable[[dict[str, float]], tuple[Any, ...]] | None = None
    """What a per-feature step reads from the row besides its feature: whether
    a condition holds, or the value it compares with."""
    selected: tuple[str, ...] = ()
    targets: tuple[str, ...] = ()
    """Where each selected feature's value goes: its own name, or an added one."""
    required: int = field(default=0)
    """Inputs before the step's first output."""


@dataclass(frozen=True)
class _Record:
    """One step's part in a pass, for diagnostics."""

    step: _Step
    values: dict[str, float] | None
    """What the step received; None when it did not run."""
    output: dict[str, float] | None
    elapsed_ns: int
    blocked_by: tuple[str, ...]
    held_back: bool
    """A Gate held the observation back here or before this step."""


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
        self.held_back = 0
        # What the last commit replaced, until the next observation runs.
        self._undo: tuple[dict[str, list[tuple]], dict[str, int], int, int] | None = (
            None
        )

    @staticmethod
    def _step(plan: ExecutionPlan, node) -> _Step:
        parents = tuple(plan.parents(node.id))
        if node.component in ROW_COMPONENTS:
            row = row_step(node.component, node.params, plan.names(parents[0]))
            return _Step(node.id, node.component, parents, dict(node.params), row=row)
        if node.component not in LANE_COMPONENTS:
            return _Step(node.id, node.component, parents, dict(node.params))
        step = kernel(node.component, node.params)
        inputs = plan.names(parents[0])
        scope = step_scope(node.component, node.params, inputs)
        return _Step(
            node.id,
            node.component,
            parents,
            dict(node.params),
            kernel=step,
            context=lane_context(node.component, node.params, inputs),
            selected=scope.selected,
            targets=scope.added if scope.add else scope.selected,
            required=step.lead + 1,
        )

    def remaining(self) -> int:
        """Observations until every chain outputs, if they all pass its Gates.

        A step outputs once it has seen its warm-up; until a step before it
        does, it waits for that step's remaining observations and then its own.
        Observations a Gate holds back advance nothing after the Gate.
        """
        remaining = {self.source_id: 0}
        for step in self.steps:
            before = max(remaining[key] for key in step.parents)
            lead = step.kernel.lead if step.kernel is not None else 0
            remaining[step.id] = (
                before + lead if before else max(lead + 1 - self.updates[step.id], 0)
            )
        return max(remaining[key] for key in self.frontier)

    @property
    def ready(self) -> bool:
        return self.remaining() == 0

    def status(self) -> dict[str, Any]:
        remaining = self.remaining()
        return {
            "ready": remaining == 0,
            "observed": max(self.required - remaining, 0),
            "required": self.required,
            "rejected": self.rejected,
            "held_back": self.held_back,
        }

    def run(
        self, bound: dict[str, float], diagnostics=None
    ) -> dict[str, float] | Withheld:
        """Prepare one observation: the learned stage's input, or why it gets none.

        Raises PrepareRejected when a step cannot produce a finite value.
        """
        self._undo = None
        available: dict[str, dict[str, float]] = {self.source_id: bound}
        staged: dict[str, list[tuple]] = {}
        records: list[_Record] = []
        # Gates that held the observation back, and the steps after them.
        held: set[str] = set()
        gate: str | None = None
        for step in self.steps:
            started = perf_counter_ns()
            # A closed Gate, like a step still warming up, has no output, so
            # the steps after it wait.
            blocked = tuple(key for key in step.parents if key not in available)
            if blocked:
                after = not held.isdisjoint(blocked)
                if after:
                    held.add(step.id)
                records.append(_Record(step, None, None, 0, blocked, after))
                continue
            values, output = self._execute(step, available, staged, diagnostics)
            closed = output is None and isinstance(step.row, Gate)
            if closed:
                held.add(step.id)
                gate = gate or step.id
            elif output is not None:
                available[step.id] = output
            elapsed = perf_counter_ns() - started
            records.append(_Record(step, values, output, elapsed, (), closed))
        self._commit(staged, records, gate)
        if diagnostics is not None:
            self._report(diagnostics, records)
        if gate is not None:
            return Withheld("held_back", gate)
        if any(key not in available for key in self.frontier):
            return Withheld("preparing")
        return {
            f"{key}.{name}": available[key][name]
            for key in self.frontier
            for name in self.names[key]
        }

    def _execute(self, step: _Step, available, staged, diagnostics):
        """The values a step shows as its input, and its output."""
        values = available[step.parents[0]]
        if step.row is not None:
            return values, self._row(step, values, diagnostics)
        if step.kernel is None:
            output = self._route(step, available)
            # A merge's inputs are its branches; its output shows them in order.
            return (output if step.component == "features.merge" else values), output
        return values, self._advance(step, values, staged, diagnostics)

    def _commit(self, staged, records: list[_Record], gate: str | None) -> None:
        # States are replaced, never changed in place, so keeping them is enough.
        self._undo = (
            {key: self.states[key] for key in staged},
            dict(self.updates),
            self.accepted,
            self.held_back,
        )
        self.states.update(staged)
        self.accepted += 1
        self.held_back += gate is not None
        for record in records:
            if record.values is not None:
                self.updates[record.step.id] += 1

    def revert(self) -> None:
        """Take back the observation run last, which a learned step then skipped.

        Afterwards the stage is as it was before that observation. Only the last
        observation can be taken back, and only once.
        """
        if self._undo is None:
            return
        states, updates, accepted, held_back = self._undo
        self.states.update(states)
        self.updates, self.accepted, self.held_back = updates, accepted, held_back
        self._undo = None

    def _reject(
        self, step: _Step, values, failure: PrepareFailure, diagnostics, name=None
    ):
        self.rejected += 1
        message = f"{name}: {failure}" if name else str(failure)
        if diagnostics is not None:
            _safely(
                diagnostics,
                diagnostics.rejected,
                step.id,
                values,
                failure.reason,
                message,
                phase="learn",
            )
        raise PrepareRejected(step.id, failure.reason, message) from failure

    def _row(self, step: _Step, values, diagnostics) -> dict[str, float] | None:
        """A row step's output; None when a Gate's condition does not hold."""
        assert step.row is not None
        try:
            if isinstance(step.row, Gate):
                return values if step.row.opens(values) else None
            return step.row.apply(values)
        except PrepareFailure as failure:
            self._reject(step, values, failure, diagnostics)

    def _advance(self, step: _Step, values, staged, diagnostics):
        assert step.kernel is not None
        states = self.states[step.id]
        advanced = []
        outputs: dict[str, float] = {}
        complete = True
        context: tuple[Any, ...] = ()
        if step.context is not None:
            try:
                context = step.context(values)
            except PrepareFailure as failure:
                self._reject(step, values, failure, diagnostics)
        for index, name in enumerate(step.selected):
            try:
                state, value = step.kernel.advance(
                    states[index], values[name], *context
                )
            except PrepareFailure as failure:
                self._reject(step, values, failure, diagnostics, name)
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

    def _report(self, diagnostics, records: list[_Record]) -> None:
        for record in records:
            step = record.step
            _safely(
                diagnostics,
                diagnostics.prepare_step,
                step.id,
                record.values,
                record.output,
                elapsed_ns=record.elapsed_ns,
                updates=self.updates[step.id] if step.kernel is not None else None,
                required=step.required or None,
                blocked_by=record.blocked_by,
                held_back=record.held_back,
            )

    def export_state(self) -> dict[str, Any]:
        """Plain data for checkpoints; states are never changed in place."""
        return {
            "version": STATE_VERSION,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "held_back": self.held_back,
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
        # Checkpoints from before Gates existed carry no held-back count.
        held_back = state.get("held_back", 0)
        counts = [
            state.get("accepted"),
            state.get("rejected"),
            held_back,
            *updates.values(),
        ]
        if not all(isinstance(value, int) and value >= 0 for value in counts):
            raise ValueError("Prepare checkpoint counts are invalid")
        self.states = {key: list(value) for key, value in states.items()}
        self.updates = dict(updates)
        self.accepted = state["accepted"]
        self.rejected = state["rejected"]
        self.held_back = held_back


def _safely(diagnostics, operation, *args, **kwargs) -> None:
    """Diagnostics never replace an execution's result or exception."""
    try:
        operation(*args, **kwargs)
    except Exception:
        diagnostics.errors += 1


__all__ = ["PrepareRejected", "PrepareStage", "Withheld"]
