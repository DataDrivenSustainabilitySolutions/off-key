"""Bound designs whose policy combines several detectors, for runtime tests."""

from __future__ import annotations

from off_key_core.models.pipelines import compile_pipeline, execution_fingerprint
from off_key_core.schemas.pipelines import (
    BoundInput,
    PipelineDefinition,
    PipelineExecutionConfig,
)
from off_key_core.utils.mqtt_topics import derive_monitoring_sensor_keys
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig

TOPICS = {"a": "telemetry/charger/a", "b": "telemetry/charger/b"}
KEYS = dict(
    zip(
        TOPICS,
        derive_monitoring_sensor_keys(
            list(TOPICS.values()), sensor_key_strategy="full_hierarchy"
        ),
        strict=True,
    )
)
STATIC_MODELS = (
    ("pyod_iforest", {"n_estimators": 10}),
    ("pyod_knn", {}),
)
ADAPTIVE_MODELS = (
    ("aberrant_moving_average_absolute_deviation", {"window_size": 10}),
    ("aberrant_moving_average_absolute_deviation", {"window_size": 10}),
)


def fused_definition(
    strategy: str = "static_baseline",
    *,
    fusion: str | None = None,
    quantile: float = 1.0,
    training: int = 30,
    calibration: int = 20,
    detectors: int = 2,
    slow_second: bool = False,
) -> PipelineDefinition:
    """Readings a and b scaled by one shared step, then a detector per reading.

    A third and fourth detector read both readings. With ``slow_second`` the
    second detector reads b through an online robust scaling that needs a few
    observations before it is ready.
    """
    adaptive = strategy == "adaptive_stream"
    family = "adaptive" if adaptive else "static"
    models = ADAPTIVE_MODELS if adaptive else STATIC_MODELS
    nodes = [
        {"id": "input", "kind": "source", "component": "source.aligned"},
        {"id": "scale", "kind": "transform", "component": f"{family}.standard_scaler"},
        {
            "id": "only_a",
            "kind": "transform",
            "component": "features.select",
            "params": {"features": ["a"]},
        },
        {
            "id": "only_b",
            "kind": "transform",
            "component": "features.select",
            "params": {"features": ["b"]},
        },
    ]
    edges = [
        {"source": "input", "target": "scale"},
        {"source": "scale", "target": "only_a"},
        {"source": "scale", "target": "only_b"},
    ]
    second_input = "only_b"
    if slow_second:
        nodes.append(
            {
                "id": "robust",
                "kind": "transform",
                "component": "adaptive.robust_scaler",
                "params": {"window_size": 20, "min_samples": 6},
            }
        )
        edges.append({"source": "only_b", "target": "robust"})
        second_input = "robust"
    inputs = ["only_a", second_input, "scale", "scale"]
    for index in range(detectors):
        identifier = "detector" if index == 0 else f"detector_{index + 1}"
        model, params = models[min(index, 1)]
        if index >= 2 and adaptive:
            model, params = "aberrant_moving_mahalanobis_distance", {"window_size": 10}
        nodes.append(
            {
                "id": identifier,
                "kind": "detector",
                "component": f"detector:{model}",
                "params": params,
            }
        )
        edges.append({"source": inputs[index], "target": identifier})
        edges.append({"source": identifier, "target": "policy", "order": index})
    policy = {"quantile": quantile} if adaptive else {}
    if fusion is not None:
        policy["fusion"] = fusion
    nodes.extend(
        [
            {
                "id": "policy",
                "kind": "policy",
                "component": "policy.quantile" if adaptive else "policy.martingale",
                "params": policy,
            },
            {"id": "output", "kind": "output", "component": "output.evidence"},
        ]
    )
    edges.append({"source": "policy", "target": "output"})
    return PipelineDefinition.model_validate(
        {
            "strategy": strategy,
            "input_slots": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "nodes": nodes,
            "edges": edges,
            "settings": {
                "training_window_size": training,
                "calibration_window_size": calibration,
            },
        }
    )


def bound(definition: PipelineDefinition) -> AnomalyDetectionConfig:
    """Bind readings a and b and compile the run's configuration."""
    definition = compile_pipeline(definition).definition
    bindings = [
        BoundInput(
            slot_id=slot,
            reading_id=f"reading-{slot}",
            entity_id="charger",
            accepted_topic=TOPICS[slot],
            input_key=KEYS[slot],
        )
        for slot in TOPICS
    ]
    return AnomalyDetectionConfig(
        pipeline=PipelineExecutionConfig(
            definition=definition,
            bindings=bindings,
            fingerprint=execution_fingerprint(definition, bindings),
            revision_id="revision",
            run_id="run",
        )
    )


def reading(a: float, b: float) -> dict[str, float]:
    return {KEYS["a"]: float(a), KEYS["b"]: float(b)}
