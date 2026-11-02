"""Deterministic lightweight compilation of saved monitoring graphs."""

from collections import defaultdict
from dataclasses import dataclass, field

from pydantic import ValidationError

from ..schemas.pipelines import (
    MAX_DETECTORS,
    MAX_PIPELINE_EXECUTION_BYTES,
    IssueFix,
    PipelineComponent,
    PipelineDefinition,
    PipelineEdge,
    PipelineIssue,
    PipelineNode,
    PipelineValidation,
)
from ..utils.json_budget import fits_json_budget
from .pipeline_catalog import pipeline_components
from .pipeline_combine import VALUE_CHECKED, value_issues
from .pipeline_digest import digest
from .pipeline_features import (
    Columns,
    adaptive_input_errors,
    node_features,
)
from .pipeline_fields import parameter_path
from .pipeline_formula import FormulaError
from .pipeline_parameters import normalized_parameters
from .pipeline_prepare import (
    LANE_COMPONENTS,
    MAX_WINDOW_VALUES,
    PREPARE_COMPONENTS,
    kernel,
)
from .pipeline_scope import LEARNED_COMPONENTS, ScopeError


@dataclass
class _Compilation:
    definition: PipelineDefinition
    nodes: dict[str, PipelineNode]
    components: dict[str, PipelineComponent]
    issues: list[PipelineIssue] = field(default_factory=list)
    incoming: dict[str, list[PipelineEdge]] = field(
        default_factory=lambda: defaultdict(list)
    )
    outgoing: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    order: list[str] = field(default_factory=list)
    features: dict[str, Columns] = field(default_factory=dict)
    unresolved: set[str] = field(default_factory=set)

    def error(
        self,
        code: str,
        message: str,
        node_id: str | None = None,
        *,
        blocks_features: bool = True,
        parameter_path: list[str | int] | None = None,
        fix: tuple[int, int, str] | None = None,
    ) -> None:
        self.issues.append(
            PipelineIssue(
                code=code,
                message=message,
                node_id=node_id,
                parameter_path=parameter_path,
                fix=None
                if fix is None
                else IssueFix(start=fix[0], end=fix[1], text=fix[2]),
            )
        )
        if node_id is not None and blocks_features:
            self.unresolved.add(node_id)

    def warning(
        self,
        code: str,
        message: str,
        node_id: str | None = None,
        *,
        parameter_path: list[str | int] | None = None,
    ) -> None:
        """Report something to review that does not stop the design from running."""
        self.issues.append(
            PipelineIssue(
                code=code,
                message=message,
                node_id=node_id,
                parameter_path=parameter_path,
                severity="warning",
            )
        )

    @property
    def valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


def _validate_identity(compilation: _Compilation) -> None:
    definition = compilation.definition
    if len(compilation.nodes) != len(definition.nodes):
        compilation.error("duplicate_node", "Node IDs must be unique")
        seen = set()
        for node in definition.nodes:
            if node.id in seen:
                compilation.unresolved.add(node.id)
            seen.add(node.id)
    slots = [slot.id for slot in definition.input_slots]
    if not slots or len(slots) != len(set(slots)):
        compilation.error(
            "input_slots", "Declare distinct input slots before publishing"
        )
        compilation.unresolved.update(
            node.id for node in definition.nodes if node.kind == "source"
        )
    for kind in ("source", "policy", "output"):
        if sum(node.kind == kind for node in definition.nodes) != 1:
            compilation.error(
                "node_count", f"An executable design requires exactly one {kind} node"
            )
    detectors = _detector_count(definition)
    if detectors == 0:
        compilation.error(
            "node_count", "An executable design requires at least one detector node"
        )
    elif detectors > MAX_DETECTORS:
        compilation.error(
            "node_count",
            f"A design can combine at most {MAX_DETECTORS} detectors; "
            f"this one has {detectors}.",
        )


def _detector_count(definition: PipelineDefinition) -> int:
    return sum(node.kind == "detector" for node in definition.nodes)


# What to write where a step's text is missing or empty.
_EMPTY_TEXT = {
    "expression": "Write a formula, such as dc_voltage * dc_current.",
    "condition": "Write a condition, such as dc_current > 1.",
}
# The characters a name may hold, in words rather than as a pattern.
_NAME_CHARACTERS = {
    "suffix": "Use letters, digits and underscores.",
    "name": "Use letters, digits and underscores, and start with a letter or "
    "an underscore.",
}


def _parameter_message(issue) -> str:
    """A validator's own sentence, without Pydantic's prefix."""
    field = issue["loc"][-1] if issue["loc"] else None
    if issue["type"] in {"missing", "string_too_short"} and field in _EMPTY_TEXT:
        return _EMPTY_TEXT[field]
    if issue["type"] == "string_pattern_mismatch" and field in _NAME_CHARACTERS:
        return _NAME_CHARACTERS[field]
    if issue["type"] == "missing":
        return "Enter a value."
    return issue["msg"].removeprefix("Value error, ")


def _validate_components(compilation: _Compilation) -> None:
    for node in compilation.definition.nodes:
        component = compilation.components.get(node.component)
        if component is None or component.kind != node.kind:
            compilation.error(
                "component", "Unknown component or incompatible node kind", node.id
            )
            continue
        if compilation.definition.strategy not in component.strategies:
            compilation.error(
                "strategy",
                "Component does not support this monitoring strategy",
                node.id,
            )
            continue
        if node.contract_version != component.contract_version:
            compilation.error(
                "component_version",
                "Component contract version is unsupported by this deployment",
                node.id,
            )
            continue
        try:
            node.params = normalized_parameters(node, compilation.definition)
        except ValidationError as exc:
            for issue in exc.errors(include_url=False, include_context=False):
                compilation.error(
                    "parameters",
                    _parameter_message(issue),
                    node.id,
                    parameter_path=parameter_path(issue["loc"], component.fields),
                )
        except (ValueError, TypeError) as exc:
            compilation.error("parameters", str(exc), node.id)


def _index_connections(compilation: _Compilation) -> None:
    seen: set[tuple[str, str]] = set()
    for edge in compilation.definition.edges:
        if edge.source not in compilation.nodes or edge.target not in compilation.nodes:
            compilation.error(
                "connection", "Connection references a missing node", edge.target
            )
            continue
        key = (edge.source, edge.target)
        if key in seen:
            compilation.error(
                "connection", "Duplicate connections are not permitted", edge.target
            )
        seen.add(key)
        compilation.incoming[edge.target].append(edge)
        compilation.outgoing[edge.source].append(edge.target)
        source = compilation.components.get(compilation.nodes[edge.source].component)
        target = compilation.components.get(compilation.nodes[edge.target].component)
        if source and target and source.output_type != target.input_type:
            compilation.error(
                "port_type",
                f"Cannot connect {source.output_type} to {target.input_type}",
                edge.target,
            )


def _validate_node_connections(compilation: _Compilation, node: PipelineNode) -> None:
    edges = compilation.incoming[node.id]
    detectors = _detector_count(compilation.definition)
    # A policy takes one connection from each detector.
    required = {"source": 0, "merge": 2, "policy": max(detectors, 1)}.get(node.kind, 1)
    if len(edges) < required or (node.kind != "merge" and len(edges) != required):
        expected = "at least two" if node.kind == "merge" else str(required)
        compilation.error(
            "input_count",
            f"policy requires one incoming connection from each of the {required} "
            "detectors"
            if node.kind == "policy" and required > 1
            else f"{node.kind} requires {expected} incoming connection(s)",
            node.id,
        )
    if node.kind == "merge" and len({edge.order for edge in edges}) != len(edges):
        compilation.error(
            "merge_order", "Merge connection order values must be distinct", node.id
        )
    if node.kind != "output" and not compilation.outgoing[node.id]:
        compilation.error(
            "disconnected",
            "Every node must reach the evidence output",
            node.id,
            blocks_features=False,
        )
    if node.kind == "output" and compilation.outgoing[node.id]:
        compilation.error(
            "output", "Evidence output cannot connect to another node", node.id
        )


def _topological_order(compilation: _Compilation) -> None:
    pending = {
        identifier: len(compilation.incoming[identifier])
        for identifier in compilation.nodes
    }
    compilation.order = sorted(
        identifier for identifier, count in pending.items() if count == 0
    )
    cursor = 0
    while cursor < len(compilation.order):
        for target in sorted(compilation.outgoing[compilation.order[cursor]]):
            pending[target] -= 1
            if pending[target] == 0:
                compilation.order.append(target)
        cursor += 1
    if len(compilation.order) != len(compilation.nodes):
        compilation.error("cycle", "Pipeline connections must form an acyclic graph")


def _propagate_features(compilation: _Compilation) -> None:
    for identifier in compilation.order:
        edges = sorted(compilation.incoming[identifier], key=lambda item: item.order)
        if identifier in compilation.unresolved or any(
            edge.source not in compilation.features for edge in edges
        ):
            continue
        node = compilation.nodes[identifier]
        branches = [(edge.source, compilation.features[edge.source]) for edge in edges]
        try:
            compilation.features[identifier] = node_features(
                compilation.definition, node, branches
            )
        except ScopeError as exc:
            compilation.error(
                "scope", str(exc), identifier, parameter_path=exc.parameter_path
            )
        except FormulaError as exc:
            compilation.error(
                "formula",
                str(exc),
                identifier,
                parameter_path=[exc.parameter] if exc.parameter else None,
                fix=exc.fix if exc.parameter else None,
            )
        except (ValueError, KeyError) as exc:
            compilation.error("feature_schema", str(exc), identifier)


def _label(compilation: _Compilation, identifier: str) -> str:
    node = compilation.nodes[identifier]
    component = compilation.components.get(node.component)
    return node.label or (component.label if component else node.component)


def _validate_stages(compilation: _Compilation) -> None:
    """Prepare steps run before anything learns, so none may follow a learned step."""
    learned: dict[str, str | None] = {}
    for identifier in compilation.order:
        node = compilation.nodes[identifier]
        edges = sorted(compilation.incoming[identifier], key=lambda item: item.order)
        upstream = next(
            (learned[edge.source] for edge in edges if learned.get(edge.source)), None
        )
        if node.component in PREPARE_COMPONENTS and upstream is not None:
            compilation.error(
                "stage",
                f"{_label(compilation, identifier)} must come before "
                f"{_label(compilation, upstream)}: prepare steps run before "
                "anything learns.",
                identifier,
                blocks_features=False,
            )
        learned[identifier] = (
            identifier if node.component in LEARNED_COMPONENTS else upstream
        )


def _validate_windows(compilation: _Compilation) -> None:
    """Bound the past values all Prepare windows keep, across their features."""
    total = 0
    for identifier, node in compilation.nodes.items():
        edges = compilation.incoming[identifier]
        if (
            node.component not in LANE_COMPONENTS
            or identifier not in compilation.features
            or len(edges) != 1
        ):
            continue
        used = node.params.get("apply_to") or compilation.features[edges[0].source]
        total += kernel(node.component, node.params).window * len(used)
    if total > MAX_WINDOW_VALUES:
        compilation.error(
            "prepare_budget",
            f"Windows hold {total:,} values; the limit is {MAX_WINDOW_VALUES:,}.",
        )


def _feature_labels(compilation: _Compilation, columns: Columns) -> dict[str, str]:
    """Readings by their label, so a message says DC current, not dc_current."""
    slots = {
        slot.id: slot.label for slot in compilation.definition.input_slots if slot.label
    }
    return {
        item.name: slots[item.name]
        for item in columns
        if item.raw and item.slots == [item.name] and item.name in slots
    }


def _validate_values(compilation: _Compilation) -> None:
    """Values a Prepare step will skip: a warning for some, an error for all."""
    for identifier in compilation.order:
        node = compilation.nodes[identifier]
        edges = compilation.incoming[identifier]
        if (
            node.component not in VALUE_CHECKED
            or identifier not in compilation.features
            or len(edges) != 1
        ):
            continue
        columns = compilation.features[edges[0].source]
        labels = _feature_labels(compilation, columns)
        for issue in value_issues(node.component, node.params, columns, labels):
            report = (
                compilation.error if issue.severity == "error" else compilation.warning
            )
            report(
                "values",
                issue.message,
                identifier,
                parameter_path=[issue.parameter],
            )


def _validate_model(compilation: _Compilation) -> None:
    if compilation.definition.strategy != "adaptive_stream":
        return
    for detector in compilation.definition.nodes:
        if detector.kind != "detector" or detector.id not in compilation.features:
            continue
        errors = adaptive_input_errors(detector, compilation.features[detector.id])
        for code, message in errors:
            compilation.error(code, message, detector.id)


def _definition_fingerprint(definition: PipelineDefinition) -> str:
    executable = definition.model_dump(mode="json")
    for slot in executable["input_slots"]:
        slot.pop("label", None)
    for node in executable["nodes"]:
        node.pop("label", None)
    executable["nodes"] = sorted(executable["nodes"], key=lambda item: item["id"])
    executable["edges"] = sorted(
        executable["edges"],
        key=lambda item: (item["target"], item["order"], item["source"]),
    )
    return digest(executable)


def validate_pipeline(definition: PipelineDefinition) -> PipelineValidation:
    """Normalize known parameters and collect errors for incomplete drafts."""
    normalized = definition.model_copy(deep=True)
    compilation = _Compilation(
        normalized,
        {node.id: node for node in normalized.nodes},
        {item.id: item for item in pipeline_components()},
    )
    _validate_identity(compilation)
    _validate_components(compilation)
    _index_connections(compilation)
    for node in normalized.nodes:
        _validate_node_connections(compilation, node)
    _topological_order(compilation)
    _propagate_features(compilation)
    _validate_stages(compilation)
    _validate_windows(compilation)
    _validate_values(compilation)
    _validate_model(compilation)
    if not fits_json_budget(normalized, MAX_PIPELINE_EXECUTION_BYTES):
        compilation.error(
            "configuration_budget",
            "Normalized definition exceeds the 96KiB execution configuration budget",
        )
    if (
        normalized.strategy == "static_baseline"
        and normalized.settings.training_window_size < 20
    ):
        compilation.error(
            "training", "Static baseline requires at least 20 training observations"
        )
    return PipelineValidation(
        valid=compilation.valid,
        issues=compilation.issues,
        definition=normalized,
        order=compilation.order,
        features=compilation.features,
        fingerprint=_definition_fingerprint(normalized) if compilation.valid else None,
    )


def compile_pipeline(definition: PipelineDefinition) -> PipelineValidation:
    result = validate_pipeline(definition)
    if not result.valid:
        raise ValueError(
            "; ".join(
                item.message for item in result.issues if item.severity == "error"
            )
        )
    return result
