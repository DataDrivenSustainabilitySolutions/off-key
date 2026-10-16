"""Feature names, lineage, widths and known domains propagated through a graph."""

from collections.abc import Callable

from ..schemas.pipelines import FeatureDescription, PipelineDefinition, PipelineNode
from .adaptive import ADAPTIVE_MODELS_BY_TYPE

Columns = list[FeatureDescription]
PROJECTIONS = {
    "static.pca",
    "adaptive.uncentered_pca",
    "static.random_projection",
    "adaptive.random_projection",
}


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


def _standard(_node: PipelineNode, columns: Columns) -> Columns:
    for item in columns:
        item.minimum = item.maximum = None
        item.raw = False
    return columns


TRANSFORMS: dict[str, Callable[[PipelineNode, Columns], Columns]] = {
    "features.select": _select,
    "features.rename": _rename,
    "static.min_max_scaler": _min_max,
    "adaptive.min_max_scaler": _min_max,
    "static.standard_scaler": _standard,
    "adaptive.standard_scaler": _standard,
}


def _projection(
    definition: PipelineDefinition, node: PipelineNode, columns: Columns
) -> Columns:
    count = node.params["n_components"]
    if count > len(columns):
        raise ValueError("n_components must not exceed incoming feature count")
    if (
        node.component == "static.pca"
        and count > definition.settings.training_window_size
    ):
        raise ValueError("PCA components exceed training observations")
    lineage = sorted({slot for item in columns for slot in item.slots})
    return [
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
    elif node.component in TRANSFORMS:
        columns = TRANSFORMS[node.component](node, columns)
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


def adaptive_readiness_errors(node: PipelineNode) -> list[tuple[str, str]]:
    retained_models = {
        "detector:aberrant_moving_geometric_average",
        "detector:aberrant_moving_harmonic_average",
    }
    if node.component in retained_models and node.params.get("window_size", 100) < 2:
        return [
            (
                "readiness",
                "This detector needs at least two retained values; "
                "window_size must be at least 2",
            )
        ]
    return []
