"""Compile feature nodes into public, standalone Aberrant components."""

from aberrant.catalog import DetectorConfig, ResolvedDetectorConfig
from aberrant.compose import INPUT, GraphNode, GraphPipeline, MergeNode

from .components import Prepared, online_component
from .plan import ExecutionPlan


def resolved_detector_config(plan: ExecutionPlan) -> ResolvedDetectorConfig:
    from off_key_core.models.adaptive import (
        ADAPTIVE_MODELS_BY_TYPE,
        bind_detector_parameters,
    )

    node = plan.nodes[plan.detector_id]
    model_type = node.component.removeprefix("detector:")
    definition = ADAPTIVE_MODELS_BY_TYPE[model_type]
    params = bind_detector_parameters(
        definition["bound_parameters"], node.params, plan.output_features
    )
    config = DetectorConfig.from_mapping(
        {
            "version": 1,
            "model": {"id": definition["catalog_id"], "params": params},
        }
    ).resolve()
    capabilities = config.capabilities
    if capabilities.higher_is_more_anomalous is not True:
        raise ValueError("Monitoring requires higher scores to mean more anomalous")
    if not capabilities.feature_count.accepts(len(plan.output_features)):
        raise ValueError("Detector does not support the compiled feature count")
    return config


def adaptive_graph(
    plan: ExecutionPlan, observer=None, config: ResolvedDetectorConfig | None = None
):
    nodes = []
    stage = plan.stage
    # Without a Prepare stage the graph keeps its shape, also in checkpoints.
    # With one, the graph's input is the prepared row and each node crossing
    # the cut, the input included, becomes a node that picks its features.
    if stage is not None:
        nodes.extend(
            GraphNode(key, Prepared(key, plan.names(key))) for key in stage.frontier
        )

    def reference(parent: str) -> str:
        return INPUT if stage is None and parent == plan.source_id else parent

    for node in plan.learned_nodes:
        parents = plan.parents(node.id)
        inputs = [reference(parent) for parent in parents]
        if node.kind == "merge":
            nodes.append(MergeNode(node.id, inputs=tuple(inputs)))
            continue
        transformer = online_component(plan, node, parents)
        nodes.append(GraphNode(node.id, transformer, input=inputs[0]))
    if config is None:
        config = resolved_detector_config(plan)
    capabilities = config.capabilities
    minimum = (
        capabilities.warmup.minimum or 0
        if capabilities.warmup.unit.value == "events"
        else 0
    )
    if minimum > plan.execution.definition.settings.training_window_size:
        raise ValueError(f"Detector warm-up must contain at least {minimum} updates")
    terminal = config.build()
    return GraphPipeline(
        nodes,
        terminal,
        reference(plan.feature_output_id),
        model_minimum_updates=minimum,
        observer=observer,
    ), config
