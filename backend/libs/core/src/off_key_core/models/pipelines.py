"""Public lightweight monitoring graph contracts and composition entry points."""

from collections.abc import Mapping, Sequence
from typing import Any

from ..schemas.pipeline_versions import component_learning
from ..schemas.pipelines import BoundInput, PipelineDefinition
from ..schemas.radar import (
    AdaptiveStreamConfig,
    FormMonitorConfig,
    StaticBaselineConfig,
)
from ..utils.mqtt_topics import (
    derive_monitoring_sensor_keys,
    normalize_static_monitoring_topics,
)
from .adaptive import ADAPTIVE_MODELS_BY_TYPE, detector_component
from .pipeline_calibration import EXCEEDANCE_RULE
from .pipeline_catalog import pipeline_catalog, pipeline_catalog_id, pipeline_components
from .pipeline_compiler import compile_pipeline, validate_pipeline
from .pipeline_digest import digest
from .pipeline_parameters import PARAMETER_MODELS, policy_settings

__all__ = [
    "PARAMETER_MODELS",
    "compile_pipeline",
    "derive_monitoring_config",
    "execution_fingerprint",
    "form_inputs",
    "lower_form_monitor",
    "pipeline_catalog",
    "pipeline_catalog_id",
    "pipeline_components",
    "validate_pipeline",
]


def derive_monitoring_config(definition: PipelineDefinition):
    """The run's monitoring settings: its first detector and the policy's own.

    A design that combines detectors reads the others from its graph, and a
    calibration step that adapts is read from there too. The policy picks the
    settings: the conformal alarm policy runs on p-values, the score threshold
    and the exceedance rule on scores. A run on scores names its first detector
    that takes in every observation, which detectors fitted once sit beside;
    when every detector is fitted once, it names the first of those.
    """
    compiled = compile_pipeline(definition)
    nodes = {node.id: node for node in compiled.definition.nodes}
    policy_node = nodes[compiled.policy_id]
    boundary = policy_node.component == EXCEEDANCE_RULE
    on_scores = boundary or policy_node.component == "policy.quantile"
    streaming = [
        identifier
        for identifier in compiled.detector_ids
        if component_learning(nodes[identifier].component) != "batch"
    ]
    detector = nodes[streaming[0] if on_scores and streaming else compiled.detector_id]
    # The exceedance rule's own settings stay in the graph.
    policy = None if boundary else policy_settings(policy_node.params)
    settings = compiled.definition.settings
    common: dict[str, Any] = dict(
        model_type=detector.component.removeprefix("detector:"),
        model_params=detector.params,
        training_window_size=settings.training_window_size,
        calibration_window_size=settings.calibration_window_size,
    )
    if on_scores and streaming:
        if policy is not None:
            common["threshold_config"] = policy
        return AdaptiveStreamConfig(**common)
    if policy is not None:
        common["martingale_config"] = policy
    return StaticBaselineConfig(
        **common, seed=settings.seed, conformal_strategy=settings.conformal_strategy
    )


def execution_fingerprint(
    definition: PipelineDefinition, bindings: Sequence[BoundInput | Mapping]
) -> str:
    normalized = [
        BoundInput.model_validate(item).model_dump(mode="json") for item in bindings
    ]
    return digest(
        {
            "graph": compile_pipeline(definition).fingerprint,
            "bindings": sorted(normalized, key=lambda item: item["slot_id"]),
        }
    )


def form_inputs(config: FormMonitorConfig) -> list[tuple[str, str]]:
    """Sensor keys with their topics, in the sorted order form detectors use."""
    topics = normalize_static_monitoring_topics(config.mqtt_topics)
    keys = derive_monitoring_sensor_keys(
        topics, sensor_key_strategy=config.performance_config.sensor_key_strategy
    )
    return sorted(zip(keys, topics, strict=True))


def lower_form_monitor(parsed: FormMonitorConfig) -> PipelineDefinition:
    """The graph equivalent of a form-configured monitor."""
    slots = [
        {"id": f"input_{index + 1}", "label": key}
        for index, (key, _) in enumerate(form_inputs(parsed))
    ]
    nodes = [{"id": "input", "kind": "source", "component": "source.aligned"}]
    previous = "input"
    edges = []
    # Form monitors clipped scaled features for unit-interval detectors.
    clip = parsed.monitoring.strategy == "adaptive_stream" and bool(
        ADAPTIVE_MODELS_BY_TYPE[parsed.monitoring.model_type]["default_capabilities"][
            "requires_unit_interval"
        ]
    )
    for index, step in enumerate(getattr(parsed.monitoring, "preprocessing_steps", [])):
        params = step.model_dump(mode="json")
        kind = params.pop("type")
        if kind == "min_max_scaler" and clip:
            params["clip"] = True
        node_id = f"transform_{index + 1}"
        component = (
            f"adaptive.{kind if kind != 'incremental_pca' else 'uncentered_pca'}"
        )
        nodes.append(
            {
                "id": node_id,
                "kind": "transform",
                "component": component,
                "params": params,
            }
        )
        edges.append({"source": previous, "target": node_id})
        previous = node_id
    policy = (
        "policy.martingale"
        if parsed.monitoring.strategy == "static_baseline"
        else "policy.quantile"
    )
    policy_params = (
        parsed.monitoring.martingale_config
        if parsed.monitoring.strategy == "static_baseline"
        else parsed.monitoring.threshold_config
    )
    nodes.extend(
        [
            {
                "id": "detector",
                "kind": "detector",
                "component": detector_component(parsed.monitoring.model_type),
                "params": parsed.monitoring.model_params,
            },
            {
                "id": "policy",
                "kind": "policy",
                "component": policy,
                "params": policy_params.model_dump(mode="json"),
            },
            {"id": "output", "kind": "output", "component": "output.evidence"},
        ]
    )
    edges.extend(
        [
            {"source": previous, "target": "detector"},
            {"source": "detector", "target": "policy"},
            {"source": "policy", "target": "output"},
        ]
    )
    return PipelineDefinition.model_validate(
        {
            "strategy": parsed.monitoring.strategy,
            "input_slots": slots,
            "nodes": nodes,
            "edges": edges,
            "settings": {
                "training_window_size": parsed.monitoring.training_window_size,
                "calibration_window_size": parsed.monitoring.calibration_window_size,
                "seed": getattr(parsed.monitoring, "seed", 42),
            },
        }
    )
