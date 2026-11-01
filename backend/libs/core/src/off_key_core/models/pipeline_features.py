"""Feature names, lineage, widths and known domains propagated through a graph."""

from collections.abc import Callable

from ..schemas.pipelines import FeatureDescription, PipelineDefinition, PipelineNode
from .adaptive import ADAPTIVE_MODELS_BY_TYPE
from .pipeline_prepare import PREPARE_COMPONENTS, prepared_bounds
from .pipeline_scope import PROJECTIONS, step_scope

Columns = list[FeatureDescription]
__all__ = ["PROJECTIONS", "Columns", "adaptive_input_errors", "node_features"]


def _select(node: PipelineNode, columns: Columns) -> Columns:
    lookup = {item.name: item for item in columns}
    return [lookup[name] for name in node.params["features"]]


def _rename(node: PipelineNode, columns: Columns) -> Columns:
    unknown = set(node.params["mapping"]) - {item.name for item in columns}
    if unknown:
        raise ValueError(f"Unknown features to rename: {', '.join(sorted(unknown))}")
    for item in columns:
        item.name = node.params["mapping"].get(item.name, item.name)
    return columns


def _min_max(node: PipelineNode, columns: Columns) -> Columns:
    bounds = node.params["feature_range"] if node.params["clip"] else (None, None)
    for item in columns:
        item.minimum, item.maximum = bounds
        item.raw = False
    return columns


def _unbounded(_node: PipelineNode, columns: Columns) -> Columns:
    for item in columns:
        item.minimum = item.maximum = None
        item.raw = False
    return columns


ROUTES: dict[str, Callable[[PipelineNode, Columns], Columns]] = {
    "features.select": _select,
    "features.rename": _rename,
}
# Learned steps that map each feature they use to one value.
ELEMENTWISE: dict[str, Callable[[PipelineNode, Columns], Columns]] = {
    "static.min_max_scaler": _min_max,
    "adaptive.min_max_scaler": _min_max,
    "static.standard_scaler": _unbounded,
    "adaptive.standard_scaler": _unbounded,
    "static.robust_scaler": _unbounded,
    "adaptive.robust_scaler": _unbounded,
}


def _prepared(node: PipelineNode, columns: Columns) -> Columns:
    for item in columns:
        item.minimum, item.maximum = prepared_bounds(
            node.component, node.params, (item.minimum, item.maximum)
        )
        item.raw = False
    return columns


def _elementwise(node: PipelineNode, columns: Columns) -> Columns:
    scope = step_scope(node.component, node.params, [item.name for item in columns])
    position = {item.name: item for item in columns}
    used = [position[name] for name in scope.selected]
    change = (
        _prepared
        if node.component in PREPARE_COMPONENTS
        else ELEMENTWISE[node.component]
    )
    if not scope.add:
        # The used columns are the incoming ones, so they change in place.
        change(node, used)
        return columns
    added = change(node, [item.model_copy(deep=True) for item in used])
    for item, name in zip(added, scope.added, strict=True):
        item.name = name
    return columns + added


def _projection(
    definition: PipelineDefinition, node: PipelineNode, columns: Columns
) -> Columns:
    scope = step_scope(node.component, node.params, [item.name for item in columns])
    used = [columns[index] for index in scope.indices]
    count = node.params["n_components"]
    if count > len(used):
        raise ValueError(
            "n_components must not exceed incoming feature count"
            if len(used) == len(columns)
            else f"n_components must not exceed the {len(used)} features it uses"
        )
    if (
        node.component == "static.pca"
        and count > definition.settings.training_window_size
    ):
        raise ValueError("PCA components exceed training observations")
    lineage = sorted({slot for item in used for slot in item.slots})
    return [columns[index] for index in scope.kept] + [
        FeatureDescription(
            name=f"{node.id}.component_{index + 1}", slots=lineage, raw=False
        )
        for index in range(count)
    ]


def node_features(
    definition: PipelineDefinition, node: PipelineNode, branches: list[Columns]
) -> Columns:
    columns = [item.model_copy(deep=True) for branch in branches for item in branch]
    if node.kind == "source":
        columns = [
            FeatureDescription(name=slot.id, slots=[slot.id])
            for slot in definition.input_slots
        ]
    elif node.component in ROUTES:
        columns = ROUTES[node.component](node, columns)
    elif node.component in ELEMENTWISE or node.component in PREPARE_COMPONENTS:
        columns = _elementwise(node, columns)
    elif node.component in PROJECTIONS:
        columns = _projection(definition, node, columns)
    if len(columns) > 100:
        raise ValueError("Intermediate feature count exceeds the 100-feature budget")
    if len({item.name for item in columns}) != len(columns):
        raise ValueError("Feature names collide; rename branches before merging")
    return columns


def _unit_interval(column: FeatureDescription) -> bool:
    return column.raw or (
        column.minimum is not None
        and column.maximum is not None
        and column.minimum >= 0
        and column.maximum <= 1
    )


def adaptive_input_errors(
    node: PipelineNode, columns: Columns
) -> list[tuple[str, str]]:
    metadata = ADAPTIVE_MODELS_BY_TYPE[node.component.removeprefix("detector:")]
    capabilities = metadata["default_capabilities"]
    counts = capabilities["feature_count"]
    errors = []
    if len(columns) < counts["minimum"] or (
        counts["maximum"] is not None and len(columns) > counts["maximum"]
    ):
        errors.append(
            (
                "model_features",
                f"Detector requires {counts['minimum']} to "
                f"{counts['maximum'] or 'unbounded'} features",
            )
        )
    if capabilities["requires_unit_interval"] and not all(
        _unit_interval(item) for item in columns
    ):
        errors.append(
            (
                "model_domain",
                "Detector requires raw [0, 1] values or an explicitly clipped "
                "min-max path for every transformed feature",
            )
        )
    return errors
