"""Change a design in small edits: add a step, connect two, set a value.

A caller that holds a design sends it with the changes it wants and gets the
changed design back with what a check says about it. Nothing is stored. Either
every edit is made or none is: an edit that names a step the design does not
have stops the whole request and says which edit it was.

The edits also keep the drawing in order, the way the editor does: a new step
gets a place beside the step it follows, and a step put on a connection gets
room between the two it joins. A design an agent builds then reads on the
canvas like one a person drew.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from ..schemas.pipeline_tools import (
    AddInput,
    AddNote,
    AddStep,
    Connect,
    DesignEditRequest,
    DesignEditResult,
    Disconnect,
    RemoveInput,
    RemoveNote,
    RemoveStep,
    ReplaceStep,
    SetLabel,
    SetParams,
    SetSettings,
)
from ..schemas.pipelines import (
    CanvasNote,
    CanvasPosition,
    InputSlot,
    PipelineComponent,
    PipelineDefinition,
    PipelineEdge,
    PipelineLayout,
    PipelineNode,
)
from .pipeline_calibration import EXCEEDANCE_RULE, calibrator_id
from .pipeline_catalog import pipeline_components
from .pipeline_compiler import validate_pipeline
from .pipeline_reports import bounded_validation_report

# The measures of the canvas, as the editor has them.
CARD_WIDTH, CARD_HEIGHT = 224, 144
GAP_X, GAP_Y = 64, 32
GRID = 16
# A note is as wide as a card. Its height follows its text.
_NOTE_LINE, _NOTE_PADDING, _NOTE_LINE_LENGTH = 20, 16, 28
_LIMITS = {
    name: PipelineDefinition.model_fields[name].metadata[0].max_length
    for name in ("nodes", "edges", "input_slots")
}
_NOTE_LIMIT = PipelineLayout.model_fields["notes"].metadata[0].max_length
# Steps that take several connections: a merge in order, the calibration step
# one from each detector.
_SEVERAL = {"merge", "calibration"}


class EditError(ValueError):
    """An edit that cannot be made as it was asked for."""


@dataclass
class _Box:
    x: float
    y: float


@dataclass
class _Design:
    definition: PipelineDefinition
    layout: PipelineLayout
    components: dict[str, PipelineComponent]
    added: list[str] = field(default_factory=list)
    also: list[str] = field(default_factory=list)

    def step(self, identifier: str) -> PipelineNode:
        for node in self.definition.nodes:
            if node.id == identifier:
                return node
        raise EditError(f"The design has no step {identifier!r}")

    def component(self, identifier: str) -> PipelineComponent:
        component = self.components.get(identifier)
        if component is None:
            raise EditError(f"The catalog has no component {identifier!r}")
        return component

    def edge(self, source: str, target: str) -> PipelineEdge | None:
        return next(
            (
                edge
                for edge in self.definition.edges
                if edge.source == source and edge.target == target
            ),
            None,
        )

    def incoming(self, target: str) -> list[PipelineEdge]:
        return sorted(
            (edge for edge in self.definition.edges if edge.target == target),
            key=lambda edge: edge.order,
        )

    def boxes(self) -> dict[str, _Box]:
        """Where each card stands; one without a place stands where the editor
        draws it."""
        return {
            node.id: _Box(place.x, place.y)
            if (place := self.layout.nodes.get(node.id))
            else _Box(index * 270, 100)
            for index, node in enumerate(self.definition.nodes)
        }

    def place(self, identifier: str, x: float, y: float) -> None:
        self.layout.nodes[identifier] = CanvasPosition(x=x, y=y)


def _snap(value: float) -> float:
    return round(value / GRID) * GRID


def _collides(boxes: list[_Box], x: float, y: float) -> bool:
    """Whether a card at x, y would touch a box or the half gap around it."""
    return any(
        abs(box.x - x) < CARD_WIDTH + GAP_X / 2
        and abs(box.y - y) < CARD_HEIGHT + GAP_Y / 2
        for box in boxes
    )


def _free_row(boxes: list[_Box], x: float, y: float) -> float:
    """The first free row at x, moving down from y."""
    for _ in range(64):
        if not _collides(boxes, x, y):
            break
        y = _snap(y + CARD_HEIGHT + GAP_Y)
    return y


def _beside(design: _Design, anchor: str | None, side: int = 1) -> tuple[float, float]:
    """A free place right of the anchor (left with side -1), or right of the
    rightmost card."""
    boxes = design.boxes()
    if not boxes:
        return 0, 0
    start = boxes.get(anchor or "") or max(boxes.values(), key=lambda box: box.x)
    x = _snap(start.x + side * (CARD_WIDTH + GAP_X))
    return x, _free_row(list(boxes.values()), x, _snap(start.y))


def _room_on_link(design: _Design, source: str, target: str) -> tuple[float, float]:
    """Room for a card on a connection: between its ends where there is space,
    otherwise a column opened at the target by moving it and all right of it."""
    boxes = design.boxes()
    start, end = boxes[source], boxes[target]
    everything = list(boxes.values())
    gap = end.x - (start.x + CARD_WIDTH)
    if gap >= CARD_WIDTH + GAP_X:
        x = _snap(start.x + CARD_WIDTH + (gap - CARD_WIDTH) / 2)
        y = _snap((start.y + end.y) / 2)
        if not _collides(everything, x, y):
            return x, y
    if end.x <= start.x:
        return _beside(design, source)
    shift = _snap(CARD_WIDTH + GAP_X)
    x, y = end.x, end.y
    for identifier, box in boxes.items():
        if box.x >= end.x:
            box.x += shift
            design.place(identifier, box.x, box.y)
    return x, _free_row(everything, x, y)


def _next_id(design: _Design, component: str) -> str:
    prefix = "".join(
        character
        if character.isascii() and (character.isalnum() or character in "_-")
        else "_"
        for character in component
    )
    taken = {node.id for node in design.definition.nodes}
    number = 1
    while f"{prefix}_{number}" in taken:
        number += 1
    return f"{prefix}_{number}"


def _was(design: _Design, node: PipelineNode) -> str:
    """The component of a step, or what it was before it was switched off."""
    remembered = design.layout.switched_off.get(node.id)
    return remembered.component if remembered else node.component


def _join(design: _Design, source: str, target: str) -> None:
    """Connect two steps as the editor does: a merge or the calibration step
    takes the connection as its last, a single input in place of the one it had."""
    edges = design.definition.edges
    incoming = design.incoming(target)
    if design.step(target).kind in _SEVERAL:
        for order, edge in enumerate(incoming):
            edge.order = order
        order = len(incoming)
    else:
        for edge in incoming:
            edges.remove(edge)
        order = 0
    if len(edges) >= _LIMITS["edges"]:
        raise EditError(f"A design holds up to {_LIMITS['edges']} connections")
    edges.append(PipelineEdge(source=source, target=target, order=order))


def _new_step(design: _Design, edit: AddStep) -> PipelineNode:
    component = design.component(edit.component)
    nodes = design.definition.nodes
    if len(nodes) >= _LIMITS["nodes"]:
        raise EditError(f"A design holds up to {_LIMITS['nodes']} steps")
    identifier = edit.id or _next_id(design, component.id)
    if any(node.id == identifier for node in nodes):
        raise EditError(f"The design already has a step {identifier!r}")
    # The second step of a kind is told from the first by its title.
    instance = 1 + sum(_was(design, node) == component.id for node in nodes)
    return PipelineNode(
        id=identifier,
        kind=component.kind,
        component=component.id,
        contract_version=component.contract_version,
        params=edit.params,
        label=edit.label or (f"{component.label} {instance}" if instance > 1 else None),
    )


def _link(design: _Design, edit: AddStep) -> PipelineEdge | None:
    """The connection a new step goes on, where it goes on one."""
    for neighbour in (edit.after, edit.before):
        if neighbour is not None:
            design.step(neighbour)
    if edit.after is None and edit.before is None:
        return None
    if edit.after is None or edit.before is None:
        return _single_link(design, edit)
    if edit.after == edit.before:
        raise EditError("A step goes between two different steps")
    return design.edge(edit.after, edit.before)


def _single_link(design: _Design, edit: AddStep) -> PipelineEdge | None:
    """With one neighbour named, a step that hands its features on goes into
    the one connection on that side, so that it does not end in a dead end."""
    component = design.component(edit.component)
    if component.kind in _SEVERAL:
        # A merge or a calibration step joins branches; it is not spliced in.
        return None
    if component.input_type is None or component.input_type != component.output_type:
        return None
    edges = design.definition.edges
    if edit.after is not None:
        candidates = [edge for edge in edges if edge.source == edit.after]
    elif edit.before is not None:
        candidates = design.incoming(edit.before)
    else:
        return None
    return candidates[0] if len(candidates) == 1 else None


def _add_step(design: _Design, edit: AddStep) -> None:
    node = _new_step(design, edit)
    link = _link(design, edit)
    if link is not None:
        x, y = _room_on_link(design, link.source, link.target)
    elif edit.after or not edit.before:
        x, y = _beside(design, edit.after)
    else:
        x, y = _beside(design, edit.before, side=-1)
    design.definition.nodes.append(node)
    design.place(node.id, x, y)
    if link is not None:
        if len(design.definition.edges) >= _LIMITS["edges"]:
            raise EditError(f"A design holds up to {_LIMITS['edges']} connections")
        # The step after keeps its place among the inputs of a merge.
        following = PipelineEdge(source=node.id, target=link.target, order=link.order)
        link.target, link.order = node.id, 0
        design.definition.edges.append(following)
    else:
        if edit.after:
            _join(design, edit.after, node.id)
        if edit.before:
            _join(design, node.id, edit.before)
    design.added.append(node.id)


def _forget(design: _Design, identifier: str) -> None:
    design.layout.switched_off.pop(identifier, None)


def _remove_step(design: _Design, edit: RemoveStep) -> None:
    node = design.step(edit.id)
    definition = design.definition
    incoming = design.incoming(node.id)
    outgoing = [edge for edge in definition.edges if edge.source == node.id]
    definition.nodes.remove(node)
    definition.edges = [
        edge for edge in definition.edges if node.id not in (edge.source, edge.target)
    ]
    design.layout.nodes.pop(node.id, None)
    _forget(design, node.id)
    component = design.components.get(node.component)
    hands_on = component is not None and component.input_type == component.output_type
    if edit.reconnect and hands_on and len(incoming) == 1:
        source = incoming[0].source
        for edge in outgoing:
            if design.edge(source, edge.target) is None:
                definition.edges.append(
                    PipelineEdge(source=source, target=edge.target, order=edge.order)
                )


def _replace_step(design: _Design, edit: ReplaceStep) -> None:
    node = design.step(edit.id)
    component = design.component(edit.component)
    node.kind = component.kind
    node.component = component.id
    node.contract_version = component.contract_version
    node.params = edit.params
    _forget(design, node.id)
    if component.kind == "calibration":
        _follow_calibration(design, component.id)


_THRESHOLD = "policy.quantile"


def _follow_calibration(design: _Design, calibration: str) -> None:
    """A calibration step and its alarm policy go together: the fixed split
    freezes a threshold, an adapting method moves a boundary to exceed. When
    a new calibration step no longer fits the policy, the policy follows."""
    adapts = calibrator_id(calibration) is not None
    for policy in design.definition.nodes:
        if policy.kind != "policy":
            continue
        if adapts and policy.component == _THRESHOLD:
            target = EXCEEDANCE_RULE
        elif not adapts and policy.component == EXCEEDANCE_RULE:
            target = _THRESHOLD
        else:
            continue
        component = design.component(target)
        old = design.component(policy.component).label
        policy.component = component.id
        policy.contract_version = component.contract_version
        policy.params = {}
        _forget(design, policy.id)
        design.also.append(
            f"The alarm policy {policy.id!r} became {component.label} in place of "
            f"{old}, which does not work with the new calibration step."
        )


def _set_params(design: _Design, edit: SetParams) -> None:
    node = design.step(edit.id)
    if node.id in design.layout.switched_off:
        raise EditError(
            f"The step {node.id!r} is switched off; its settings are kept in the layout"
        )
    params = {**node.params, **edit.params}
    for name in edit.unset:
        params.pop(name, None)
    node.params = params


def _set_label(design: _Design, edit: SetLabel) -> None:
    node = design.step(edit.id)
    node.label = (edit.label or "").strip() or None


def _connect(design: _Design, edit: Connect) -> None:
    design.step(edit.source)
    design.step(edit.target)
    if edit.source == edit.target:
        raise EditError("A step cannot connect to itself")
    if design.edge(edit.source, edit.target) is not None:
        raise EditError(f"{edit.source!r} and {edit.target!r} are connected already")
    _join(design, edit.source, edit.target)


def _disconnect(design: _Design, edit: Disconnect) -> None:
    edge = design.edge(edit.source, edit.target)
    if edge is None:
        raise EditError(
            f"There is no connection from {edit.source!r} to {edit.target!r}"
        )
    design.definition.edges.remove(edge)


def _add_input(design: _Design, edit: AddInput) -> None:
    slots = design.definition.input_slots
    if any(slot.id == edit.id for slot in slots):
        raise EditError(f"The design already has an input {edit.id!r}")
    if len(slots) >= _LIMITS["input_slots"]:
        raise EditError(f"A design takes in up to {_LIMITS['input_slots']} readings")
    slots.append(InputSlot(id=edit.id, label=edit.label or edit.id, unit=edit.unit))


def _remove_input(design: _Design, edit: RemoveInput) -> None:
    slots = design.definition.input_slots
    kept = [slot for slot in slots if slot.id != edit.id]
    if len(kept) == len(slots):
        raise EditError(f"The design has no input {edit.id!r}")
    design.definition.input_slots = kept


def _set_settings(design: _Design, edit: SetSettings) -> None:
    settings = design.definition.settings
    for name in ("training_window_size", "calibration_window_size", "seed"):
        value = getattr(edit, name)
        if value is not None:
            setattr(settings, name, value)


def _note_height(text: str) -> float:
    lines = sum(
        max(1, math.ceil(len(line) / _NOTE_LINE_LENGTH)) for line in text.split("\n")
    )
    return lines * _NOTE_LINE + _NOTE_PADDING


def _add_note(design: _Design, edit: AddNote) -> None:
    text = edit.text.strip()
    if not text:
        raise EditError("A note says something")
    notes = design.layout.notes
    if len(notes) >= _NOTE_LIMIT:
        raise EditError(f"A design holds up to {_NOTE_LIMIT} notes")
    boxes = design.boxes()
    if edit.beside is not None:
        design.step(edit.beside)
        anchor = boxes[edit.beside]
    else:
        # Above the first card of the drawing, where a reader starts.
        anchor = min(boxes.values(), key=lambda box: (box.x, box.y), default=_Box(0, 0))
    height = _note_height(text)
    x = _snap(anchor.x)
    # The note ends a grid line above its card, and above a note already there.
    top = _snap(anchor.y) - GRID - math.ceil(height / GRID) * GRID
    for _ in range(_NOTE_LIMIT):
        covered = [
            note
            for note in notes
            if abs(note.x - x) < CARD_WIDTH
            and note.y < top + height
            and top < note.y + _note_height(note.text)
        ]
        if not covered:
            break
        top = min(note.y for note in covered) - GRID - math.ceil(height / GRID) * GRID
    taken = {note.id for note in notes}
    number = len(notes) + 1
    while f"note_{number}" in taken:
        number += 1
    notes.append(CanvasNote(id=f"note_{number}", x=x, y=top, text=text))
    design.added.append(f"note_{number}")


def _remove_note(design: _Design, edit: RemoveNote) -> None:
    notes = design.layout.notes
    kept = [note for note in notes if note.id != edit.id]
    if len(kept) == len(notes):
        raise EditError(f"The design has no note {edit.id!r}")
    design.layout.notes = kept


_APPLY: dict[type, Callable[[_Design, Any], None]] = {
    AddStep: _add_step,
    RemoveStep: _remove_step,
    ReplaceStep: _replace_step,
    SetParams: _set_params,
    SetLabel: _set_label,
    Connect: _connect,
    Disconnect: _disconnect,
    AddInput: _add_input,
    RemoveInput: _remove_input,
    SetSettings: _set_settings,
    AddNote: _add_note,
    RemoveNote: _remove_note,
}


def edit_design(request: DesignEditRequest) -> DesignEditResult:
    """Make the edits in order and check the design that results.

    Raises ``EditError`` for an edit that cannot be made, naming it by its
    place in the list. A design that results but would not run is no error:
    its issues are in the report, as they are for a draft in the editor.
    """
    design = _Design(
        request.definition.model_copy(deep=True),
        request.layout.model_copy(deep=True),
        {component.id: component for component in pipeline_components()},
    )
    for number, edit in enumerate(request.edits, start=1):
        try:
            _APPLY[type(edit)](design, edit)
        except EditError as exc:
            raise EditError(f"Edit {number} ({edit.op}): {exc}") from exc
        except ValidationError as exc:
            reason = exc.errors(include_url=False)[0]["msg"]
            raise EditError(f"Edit {number} ({edit.op}): {reason}") from exc
    validation = validate_pipeline(design.definition)
    return DesignEditResult(
        # With the defaults of every setting, as the check filled them in.
        definition=validation.definition,
        layout=design.layout,
        added=design.added,
        also=design.also,
        report=bounded_validation_report(validation, include_definition=False),
    )
