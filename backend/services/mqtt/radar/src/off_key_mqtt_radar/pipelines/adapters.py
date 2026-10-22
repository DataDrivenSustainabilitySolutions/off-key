"""Compile feature nodes into public, standalone Aberrant components."""

from contextlib import contextmanager

from aberrant.catalog import DetectorConfig, create_model
from aberrant.compose import (
    INPUT,
    GraphNode,
    GraphPipeline,
    MergeNode,
    Passthrough,
    Rename,
    Select,
)
from aberrant.transform.preprocessing import MinMaxScaler, StandardScaler
from aberrant.transform.projection import IncrementalPCA, RandomProjection

from .plan import ExecutionPlan


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


def detector_config(plan: ExecutionPlan) -> DetectorConfig:
    from off_key_core.models.adaptive import ADAPTIVE_MODELS_BY_TYPE

    node = plan.nodes[plan.detector_id]
    model_type = node.component.removeprefix("detector:")
    definition = ADAPTIVE_MODELS_BY_TYPE[model_type]
    params = dict(node.params)
    names = plan.output_features
    for name in definition["bound_parameters"]:
        params[name] = (
            True if name == "abs_diff" else names[0] if name == "key" else names
        )
    config = DetectorConfig.from_mapping(
        {
            "version": 1,
            "model": {"id": definition["catalog_id"], "params": params},
        }
    ).normalized()
    capabilities = config.capabilities()
    if capabilities.higher_is_more_anomalous is not True:
        raise ValueError("Monitoring requires higher scores to mean more anomalous")
    if not capabilities.feature_count.accepts(len(names)):
        raise ValueError("Detector does not support the compiled feature count")
    return config


def adaptive_graph(plan: ExecutionPlan, observer=None):
    nodes = []
    for node in plan.feature_nodes:
        parents = plan.parents(node.id)
        inputs = [INPUT if parent == plan.source_id else parent for parent in parents]
        params = dict(node.params)
        if node.kind == "merge":
            nodes.append(MergeNode(node.id, inputs=tuple(inputs)))
            continue
        component = node.component
        if component == "features.select":
            transformer = Select(**params)
        elif component == "features.rename":
            transformer = Rename(**params)
        elif component == "features.passthrough":
            transformer = Passthrough()
        elif component == "adaptive.standard_scaler":
            transformer = StandardScaler(**params)
        elif component == "adaptive.min_max_scaler":
            transformer = MinMaxScaler(**params)
        elif component in {"adaptive.uncentered_pca", "adaptive.random_projection"}:
            constructor = (
                IncrementalPCA
                if component == "adaptive.uncentered_pca"
                else RandomProjection
            )
            transformer = NamedProjection(
                constructor(keys=plan.names(parents[0]), **params), plan.names(node.id)
            )
        else:
            raise ValueError(f"Unsupported adaptive component: {component}")
        nodes.append(GraphNode(node.id, transformer, input=inputs[0]))
    config = detector_config(plan)
    capabilities = config.capabilities()
    minimum = (
        capabilities.warmup.minimum or 0
        if capabilities.warmup.unit.value == "events"
        else 0
    )
    if minimum > plan.execution.definition.settings.training_window_size:
        raise ValueError(f"Detector warm-up must contain at least {minimum} updates")
    terminal = create_model(config.model.id, config.model.params)
    output = plan.feature_output_id
    return GraphPipeline(
        nodes,
        terminal,
        INPUT if output == plan.source_id else output,
        model_minimum_updates=minimum,
        observer=observer,
    ), config
