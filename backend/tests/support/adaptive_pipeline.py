"""Bound adaptive pipeline executions for runtime tests."""

from __future__ import annotations

from off_key_core.models.pipelines import compile_pipeline, execution_fingerprint
from off_key_core.schemas.pipelines import (
    BoundInput,
    PipelineDefinition,
    PipelineExecutionConfig,
)
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig


def adaptive_pipeline_config(
    *,
    model="aberrant_moving_covariance",
    branched=True,
    clipped=False,
    model_params=None,
):
    slots = ["a", "b", "temperature"] if branched else ["a"]
    nodes = [{"id": "input", "kind": "source", "component": "source.aligned"}]
    edges = []
    if branched:
        nodes.extend(
            [
                {
                    "id": "selected",
                    "kind": "transform",
                    "component": "features.select",
                    "params": {"features": ["a", "b"]},
                },
                {
                    "id": "scaled",
                    "kind": "transform",
                    "component": "adaptive.min_max_scaler"
                    if clipped
                    else "adaptive.standard_scaler",
                    "params": {"clip": True} if clipped else {},
                },
                {
                    "id": "raw",
                    "kind": "transform",
                    "component": "features.select",
                    "params": {"features": ["temperature"]},
                },
                {"id": "joined", "kind": "merge", "component": "features.merge"},
            ]
        )
        edges.extend(
            [
                {"source": "input", "target": "selected"},
                {"source": "selected", "target": "scaled"},
                {"source": "input", "target": "raw"},
                {"source": "raw", "target": "joined", "order": 1},
            ]
        )
        if clipped:
            edges.append({"source": "scaled", "target": "joined", "order": 0})
        else:
            nodes.append(
                {
                    "id": "pca",
                    "kind": "transform",
                    "component": "adaptive.uncentered_pca",
                    "params": {"n_components": 1, "n0": 3},
                }
            )
            edges.extend(
                [
                    {"source": "scaled", "target": "pca"},
                    {"source": "pca", "target": "joined", "order": 0},
                ]
            )
    params = (
        {"n_trees": 1, "height": 2, "window_size": 2, "seed": 1}
        if model == "aberrant_half_space_trees"
        else {"window_size": 5}
    )
    if model_params is not None:
        params = model_params
    nodes.extend(
        [
            {
                "id": "model",
                "kind": "detector",
                "component": f"detector:{model}",
                "params": params,
            },
            {
                "id": "policy",
                "kind": "policy",
                "component": "policy.quantile",
                "params": {"quantile": 1.0},
            },
            {"id": "output", "kind": "output", "component": "output.evidence"},
        ]
    )
    edges.extend(
        [
            {"source": "joined" if branched else "input", "target": "model"},
            {"source": "model", "target": "policy"},
            {"source": "policy", "target": "output"},
        ]
    )
    definition = compile_pipeline(
        PipelineDefinition.model_validate(
            {
                "strategy": "adaptive_stream",
                "input_slots": [{"id": key, "label": key.title()} for key in slots],
                "nodes": nodes,
                "edges": edges,
                "settings": {"training_window_size": 2, "calibration_window_size": 2},
            }
        )
    ).definition
    bindings = [
        BoundInput(
            slot_id=slot,
            reading_id=f"reading-{slot}",
            entity_id="charger",
            accepted_topic=f"telemetry/charger/{slot}",
            input_key=f"reading_{slot}",
        )
        for slot in slots
    ]
    execution = PipelineExecutionConfig(
        definition=definition,
        bindings=bindings,
        run_id="run",
        revision_id="revision",
        fingerprint=execution_fingerprint(definition, bindings),
    )
    return AnomalyDetectionConfig(pipeline=execution, checkpoint_interval=1_000_000)
