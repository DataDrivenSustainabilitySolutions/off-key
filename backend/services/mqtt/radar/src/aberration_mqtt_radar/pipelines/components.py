"""Runtime constructors for every pipeline component core's catalog offers.

Core decides which components a strategy allows; this registry says how the
static batch graph and the adaptive streaming graph build each one.
tests/test_pipeline_runtime_registry.py keeps the two in step.
"""

from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

from aberrant.compose import Passthrough, Rename, Select
from aberrant.transform.preprocessing import MinMaxScaler as OnlineMinMaxScaler
from aberrant.transform.preprocessing import RollingRobustScaler
from aberrant.transform.preprocessing import StandardScaler as OnlineStandardScaler
from aberrant.transform.projection import IncrementalPCA, RandomProjection
from aberration_core.models.pipeline_scope import (
    StepScope,
    is_scoped,
    split_scope,
    step_scope,
)
from sklearn.decomposition import PCA
from sklearn.preprocessing import MinMaxScaler, RobustScaler, StandardScaler
from sklearn.random_projection import SparseRandomProjection

from .plan import ExecutionPlan

# Column operations BatchFeatureGraph applies inline, without a fitted object.
BATCH_PASSTHROUGH = frozenset(
    {"features.select", "features.rename", "features.passthrough", "features.merge"}
)


def _seeded(constructor: Callable[..., Any]) -> Callable[[dict], Any]:
    def build(params: dict) -> Any:
        params = dict(params)
        seed = params.pop("seed", None)
        return constructor(random_state=seed, **params)

    return build


BATCH_BUILDERS: dict[str, Callable[[dict], Any]] = {
    "static.standard_scaler": lambda params: StandardScaler(**params),
    "static.min_max_scaler": lambda params: MinMaxScaler(**params),
    # Median and interquartile range; a zero range divides by 1, as online.
    "static.robust_scaler": lambda params: RobustScaler(**params),
    "static.pca": _seeded(PCA),
    "static.random_projection": _seeded(SparseRandomProjection),
}


class Prepared(Passthrough):
    """Hand one Prepare-stage node's features to the learned graph.

    The learned graph's input holds every feature crossing the stage cut as
    <node>.<feature>; this node picks one node's features under their names.
    """

    def __init__(self, node_id: str, names: list[str]):
        self.prefix = f"{node_id}."
        self.names = tuple(names)

    def transform_one(self, x):
        return {name: x[self.prefix + name] for name in self.names}


class NamedProjection:
    """Adapt public projection output names to canonical graph-scoped names."""

    def __init__(self, projection, names: list[str]):
        self.projection = projection
        self.names = tuple(names)

    @property
    def readiness(self):
        return self.projection.readiness

    def learn_one(self, data):
        self.projection.learn_one(data)

    def transform_one(self, data):
        transformed = self.projection.transform_one(data)
        return {
            name: transformed[f"component_{index}"]
            for index, name in enumerate(self.names)
        }

    @contextmanager
    def learning_transaction(self, data):
        with self.projection.learning_transaction(data):
            yield


class ScopedStep:
    """Run a learned step on the features it uses; the others pass unchanged.

    Elementwise steps replace their features in place or add renamed copies;
    projections drop the features they use, unless they add, and append their
    components. The order matches the compiled feature names.
    """

    def __init__(self, transformer, scope: StepScope):
        self.transformer = transformer
        self.selected = scope.selected
        self.add = scope.add
        self.elementwise = scope.elementwise
        # Where each used feature's value goes: in place, or to its added name.
        self.targets = dict(
            zip(
                scope.selected,
                scope.added if scope.add else scope.selected,
                strict=False,
            )
        )

    @property
    def readiness(self):
        return self.transformer.readiness

    def _used(self, data: dict[str, float]) -> dict[str, float]:
        return {name: data[name] for name in self.selected}

    def learn_one(self, data):
        self.transformer.learn_one(self._used(data))

    def transform_one(self, data):
        output = self.transformer.transform_one(self._used(data))
        if self.elementwise:
            # Updating a key keeps its position; added names are appended in order.
            return {
                **data,
                **{self.targets[name]: output[name] for name in self.selected},
            }
        used = set(self.selected)
        kept = data if self.add else {k: v for k, v in data.items() if k not in used}
        return {**kept, **output}

    @contextmanager
    def learning_transaction(self, data):
        with self.transformer.learning_transaction(self._used(data)):
            yield


OnlineBuilder = Callable[[ExecutionPlan, Any, list[str], dict], Any]


def _projection(constructor: Callable[..., Any]) -> OnlineBuilder:
    def build(plan: ExecutionPlan, node, parents: list[str], params: dict) -> Any:
        scope = step_scope(node.component, node.params, plan.names(parents[0]))
        # The components are the step's last output names, after any kept features.
        components = plan.names(node.id)[len(scope.output_names()) :]
        return NamedProjection(
            constructor(keys=list(scope.selected), **params), components
        )

    return build


# features.merge is a MergeNode in the adaptive graph, not a transformer.
ONLINE_BUILDERS: dict[str, OnlineBuilder] = {
    "features.select": lambda _plan, _node, _parents, params: Select(**params),
    "features.rename": lambda _plan, _node, _parents, params: Rename(**params),
    "features.passthrough": lambda _plan, _node, _parents, _params: Passthrough(),
    "adaptive.standard_scaler": lambda _plan, _node, _parents, params: (
        OnlineStandardScaler(**params)
    ),
    "adaptive.min_max_scaler": lambda _plan, _node, _parents, params: (
        OnlineMinMaxScaler(**params)
    ),
    "adaptive.robust_scaler": lambda _plan, _node, _parents, params: (
        RollingRobustScaler(**params)
    ),
    "adaptive.uncentered_pca": _projection(IncrementalPCA),
    "adaptive.random_projection": _projection(RandomProjection),
}


def batch_component(node) -> Any:
    try:
        build = BATCH_BUILDERS[node.component]
    except KeyError:
        raise ValueError(f"Unsupported static component: {node.component}") from None
    return build(split_scope(dict(node.params))[1])


def online_component(plan: ExecutionPlan, node, parents: list[str]) -> Any:
    try:
        build = ONLINE_BUILDERS[node.component]
    except KeyError:
        raise ValueError(f"Unsupported adaptive component: {node.component}") from None
    transformer = build(plan, node, parents, split_scope(dict(node.params))[1])
    # Unscoped steps keep their plain runtime shape, also in checkpoints.
    if not is_scoped(node.component, node.params):
        return transformer
    return ScopedStep(
        transformer, step_scope(node.component, node.params, plan.names(parents[0]))
    )


__all__ = [
    "BATCH_BUILDERS",
    "BATCH_PASSTHROUGH",
    "ONLINE_BUILDERS",
    "NamedProjection",
    "Prepared",
    "ScopedStep",
    "batch_component",
    "online_component",
]
