"""Feature names, lineage, widths and known domains propagated through a graph."""

from collections.abc import Callable, Sequence

from ..schemas.pipelines import FeatureDescription, PipelineDefinition, PipelineNode
from .adaptive import ADAPTIVE_MODELS_BY_TYPE
from .pipeline_combine import (
    calculated_names,
    combined_columns,
    combined_name,
    each_scope,
    for_each,
    lane_condition,
)
from .pipeline_prepare import LANE_COMPONENTS, ROW_COMPONENTS, prepared_bounds
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
        name = node.params["mapping"].get(item.name, item.name)
        if name != item.name:
            item.name = name
            item.steps.append(node.id)
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
    names = [item.name for item in columns]
    scope = step_scope(node.component, node.params, names)
    # A condition the step reads from the row names features that arrive.
    lane_condition(node.component, node.params, names)
    position = {item.name: item for item in columns}
    used = [position[name] for name in scope.selected]
    change = (
        _prepared if node.component in LANE_COMPONENTS else ELEMENTWISE[node.component]
    )
    # Without added features the used columns are the incoming ones, so they
    # change in place.
    changed = change(
        node, [item.model_copy(deep=True) for item in used] if scope.add else used
    )
    for item in changed:
        item.steps.append(node.id)
    if node.component == "prepare.relation":
        # Each result also comes from the feature it is compared with.
        other = position[node.params["against"]].slots
        for item in changed:
            item.slots = sorted({*item.slots, *other})
    if not scope.add:
        return columns
    for item, name in zip(changed, scope.added, strict=True):
        item.name = name
    return columns + changed


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


def _continued(branches: Sequence[tuple[str, Columns]]) -> Columns:
    """Copies of the arriving features that name the feature each continues.
    Node ids hold no dots, so the first dot of node.name ends the node."""
    return [
        item.model_copy(deep=True, update={"previous": f"{parent}.{item.name}"})
        for parent, branch in branches
        for item in branch
    ]


def _combined(node: PipelineNode, columns: Columns) -> Columns:
    """A row step's features, with the step on the trail of those it changed."""
    result = combined_columns(node.component, node.params, columns)
    changed: set[str] = set()
    if for_each(node.component, node.params):
        # A formula for each feature changes features that follow a reading.
        changed.update(each_scope(node.params, [item.name for item in columns]).targets)
    elif node.component == "prepare.set":
        # A feature Set replaced from its own value continues its trail.
        changed.add(combined_name(node.component, node.params))
    elif node.component == "prepare.calculate":
        changed.update(calculated_names(node.params))
    for item in result:
        if item.name in changed and item.previous is not None:
            item.steps.append(node.id)
    return result


def _changed(
    definition: PipelineDefinition, node: PipelineNode, columns: Columns
) -> Columns:
    """What the node makes of the features that arrive."""
    if node.kind == "source":
        return [
            FeatureDescription(name=slot.id, slots=[slot.id])
            for slot in definition.input_slots
        ]
    if node.component in ROUTES:
        return ROUTES[node.component](node, columns)
    if node.component in ELEMENTWISE or node.component in LANE_COMPONENTS:
        return _elementwise(node, columns)
    if node.component in ROW_COMPONENTS:
        return _combined(node, columns)
    if node.component in PROJECTIONS:
        return _projection(definition, node, columns)
    return columns


def node_features(
    definition: PipelineDefinition,
    node: PipelineNode,
    branches: Sequence[tuple[str, Columns]],
) -> Columns:
    """The features a node gives, from its parents' features in input order."""
    if node.kind in {"calibration", "policy"} and len(branches) > 1:
        # Scores arrive here, one per detector; no feature goes further.
        return []
    columns = _changed(definition, node, _continued(branches))
    for item in columns:
        if item.previous is None and node.kind != "source":
            # Made here: an Aggregate's or Formula's feature, or a component.
            item.steps = [node.id]
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
