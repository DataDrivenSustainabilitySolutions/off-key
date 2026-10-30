"""Deterministic lightweight compilation of saved monitoring graphs."""

from collections import defaultdict
from dataclasses import dataclass, field

from pydantic import ValidationError

from ..schemas.pipelines import (
    MAX_PIPELINE_EXECUTION_BYTES,
    PipelineComponent,
    PipelineDefinition,
    PipelineEdge,
    PipelineIssue,
    PipelineNode,
    PipelineValidation,
)
from ..utils.json_budget import fits_json_budget
from .pipeline_catalog import pipeline_components
from .pipeline_digest import digest
from .pipeline_features import (
    Columns,
    adaptive_input_errors,
    node_features,
)
from .pipeline_fields import parameter_path
from .pipeline_parameters import normalized_parameters


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
    ) -> None:
        self.issues.append(
            PipelineIssue(
                code=code,
                message=message,
                node_id=node_id,
                parameter_path=parameter_path,
            )
        )
        if node_id is not None and blocks_features:
            self.unresolved.add(node_id)


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
    for kind in ("source", "detector", "policy", "output"):
        if sum(node.kind == kind for node in definition.nodes) != 1:
            compilation.error(
                "node_count", f"An executable design requires exactly one {kind} node"
            )


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
                    issue["msg"],
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
    required = {"source": 0, "merge": 2}.get(node.kind, 1)
    if len(edges) < required or (node.kind != "merge" and len(edges) != required):
        expected = "at least two" if node.kind == "merge" else str(required)
        compilation.error(
            "input_count",
            f"{node.kind} requires {expected} incoming connection(s)",
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
        branches = [compilation.features[edge.source] for edge in edges]
        try:
            compilation.features[identifier] = node_features(
                compilation.definition, node, branches
            )
        except (ValueError, KeyError) as exc:
            compilation.error("feature_schema", str(exc), identifier)


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
        valid=not compilation.issues,
        issues=compilation.issues,
        definition=normalized,
        order=compilation.order,
        features=compilation.features,
        fingerprint=_definition_fingerprint(normalized)
        if not compilation.issues
        else None,
    )


def compile_pipeline(definition: PipelineDefinition) -> PipelineValidation:
    result = validate_pipeline(definition)
    if not result.valid:
        raise ValueError("; ".join(item.message for item in result.issues))
    return result
