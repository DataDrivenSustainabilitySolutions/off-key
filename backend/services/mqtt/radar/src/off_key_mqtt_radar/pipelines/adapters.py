"""Compile feature nodes into public, standalone Aberrant components."""

from aberrant.catalog import DetectorConfig, ResolvedDetectorConfig
from aberrant.compose import INPUT, GraphNode, GraphPipeline, MergeNode

from .components import Prepared, online_component
from .plan import ExecutionPlan


def resolved_detector_config(
    plan: ExecutionPlan, detector_id: str | None = None
) -> ResolvedDetectorConfig:
    from off_key_core.models.adaptive import (
        ADAPTIVE_MODELS_BY_TYPE,
        PRETRAINED_FORECASTERS,
        RULE_DETECTORS,
        aberrant_model,
        bind_detector_parameters,
    )

    detector_id = detector_id or plan.detector_id
    node = plan.nodes[detector_id]
    features = plan.detector_features(detector_id)
    model_type = node.component.removeprefix("detector:")
    definition = ADAPTIVE_MODELS_BY_TYPE[model_type]
    params = bind_detector_parameters(
        definition["bound_parameters"], node.params, features
    )
    # A null detector seed inherits the saved design's default, as feature
    # transforms do. Resolve it here to preserve existing graph fingerprints.
    if "seed" in params and params["seed"] is None:
        params["seed"] = plan.compiled.definition.settings.seed
    if model_type in PRETRAINED_FORECASTERS:
        from ..forecasting import resolve_service_detector

        # Its settings are not Aberrant's to complete, so the defaults go in here.
        config = resolve_service_detector(
            aberrant_model(definition, definition["default_parameters"] | params)
        )
    elif model_type in RULE_DETECTORS:
        from ..rules import resolve_rule_detector

        config = resolve_rule_detector(aberrant_model(definition, params))
    else:
        config = DetectorConfig.from_mapping(
            {"version": 1, "model": aberrant_model(definition, params)}
        ).resolve()
    capabilities = config.capabilities
    if capabilities.higher_is_more_anomalous is not True:
        raise ValueError("Monitoring requires higher scores to mean more anomalous")
    if not capabilities.feature_count.accepts(len(features)):
        raise ValueError("Detector does not support the compiled feature count")
    return config


def adaptive_graph(
    plan: ExecutionPlan,
    observer=None,
    config: ResolvedDetectorConfig | None = None,
    detector_id: str | None = None,
):
    """One detector's Aberrant graph with every learned step it reads.

    With several detectors each one gets a graph with its own copy of the
    steps it reads, so a step two detectors share learns twice, identically.
    """
    detector_id = detector_id or plan.detector_id
    # One detector reads every node; several keep to their own branches.
    needed = plan.reads(detector_id) if plan.fused else None
    nodes = []
    stage = plan.stage
    learned = [
        node for node in plan.learned_nodes if needed is None or node.id in needed
    ]
    # Without a Prepare stage the graph keeps its shape, also in checkpoints.
    # With one, the graph's input is the prepared row and each node crossing
    # the cut, the input included, becomes a node that picks its features.
    if stage is not None:
        # Only what this graph reads across the cut: the input reaches a
        # detector behind a Prepare step through that step alone.
        crossing = {plan.detector_inputs[detector_id]}.union(
            *(plan.parents(node.id) for node in learned)
        )
        nodes.extend(
            GraphNode(key, Prepared(key, plan.names(key)))
            for key in stage.frontier
            if key in crossing
        )

    def reference(parent: str) -> str:
        return INPUT if stage is None and parent == plan.source_id else parent

    for node in learned:
        parents = plan.parents(node.id)
        inputs = [reference(parent) for parent in parents]
        if node.kind == "merge":
            nodes.append(MergeNode(node.id, inputs=tuple(inputs)))
            continue
        transformer = online_component(plan, node, parents)
        nodes.append(GraphNode(node.id, transformer, input=inputs[0]))
    if config is None:
        config = resolved_detector_config(plan, detector_id)
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
        reference(plan.detector_inputs[detector_id]),
        model_minimum_updates=minimum,
        observer=observer,
    ), config
