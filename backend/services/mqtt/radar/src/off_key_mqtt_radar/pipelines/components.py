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
from aberrant.transform.preprocessing import StandardScaler as OnlineStandardScaler
from aberrant.transform.projection import IncrementalPCA, RandomProjection
from sklearn.decomposition import PCA
from sklearn.preprocessing import MinMaxScaler, StandardScaler
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
    "static.pca": _seeded(PCA),
    "static.random_projection": _seeded(SparseRandomProjection),
}


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


OnlineBuilder = Callable[[ExecutionPlan, Any, list[str], dict], Any]


def _projection(constructor: Callable[..., Any]) -> OnlineBuilder:
    def build(plan: ExecutionPlan, node, parents: list[str], params: dict) -> Any:
        return NamedProjection(
            constructor(keys=plan.names(parents[0]), **params), plan.names(node.id)
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
    "adaptive.uncentered_pca": _projection(IncrementalPCA),
    "adaptive.random_projection": _projection(RandomProjection),
}


def batch_component(node) -> Any:
    try:
        build = BATCH_BUILDERS[node.component]
    except KeyError:
        raise ValueError(f"Unsupported static component: {node.component}") from None
    return build(dict(node.params))


def online_component(plan: ExecutionPlan, node, parents: list[str]) -> Any:
    try:
        build = ONLINE_BUILDERS[node.component]
    except KeyError:
        raise ValueError(f"Unsupported adaptive component: {node.component}") from None
    return build(plan, node, parents, dict(node.params))


__all__ = [
    "BATCH_BUILDERS",
    "BATCH_PASSTHROUGH",
    "ONLINE_BUILDERS",
    "NamedProjection",
    "batch_component",
    "online_component",
]
