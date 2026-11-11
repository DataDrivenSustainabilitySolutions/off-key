"""Designs whose calibration step keeps adapting, for compiler and runtime tests."""

from __future__ import annotations

from off_key_core.schemas.pipelines import PipelineDefinition

MAD = "detector:aberrant_moving_average_absolute_deviation"
FOREST = "detector:pyod_iforest"
TRAINING, CALIBRATION = 30, 20
# Reading a goes scaled once into a PyOD detector, reading b scaled online into MAD.
BRANCHES = {
    "forest": ("a", "static.standard_scaler", FOREST, {"n_estimators": 10}),
    "knn": ("a", "static.standard_scaler", "detector:pyod_knn", {}),
    "mad": ("b", "adaptive.standard_scaler", MAD, {"window_size": 10}),
}


def boundary_definition(
    detectors: tuple[str, ...] = ("forest", "mad"),
    *,
    calibration: str = "calibrate.aci",
    params: dict | None = None,
    policy: str = "policy.exceedance",
    policy_params: dict | None = None,
    calibration_window: int = CALIBRATION,
) -> PipelineDefinition:
    """One branch per detector, meeting at one calibration step and its policy."""
    nodes = [{"id": "input", "kind": "source", "component": "source.aligned"}]
    edges = []
    for order, name in enumerate(detectors):
        reading, scaler, component, settings = BRANCHES[name]
        nodes += [
            {
                "id": f"only_{reading}",
                "kind": "transform",
                "component": "features.select",
                "params": {"features": [reading]},
            },
            {"id": f"scale_{reading}", "kind": "transform", "component": scaler},
            {
                "id": name,
                "kind": "detector",
                "component": component,
                "params": settings,
            },
        ]
        edges += [
            {"source": "input", "target": f"only_{reading}"},
            {"source": f"only_{reading}", "target": f"scale_{reading}"},
            {"source": f"scale_{reading}", "target": name},
            {"source": name, "target": "calibrate", "order": order},
        ]
    nodes += [
        {
            "id": "calibrate",
            "kind": "calibration",
            "component": calibration,
            "params": {"alpha": 0.1} if params is None else params,
        },
        {
            "id": "policy",
            "kind": "policy",
            "component": policy,
            "params": policy_params or {},
        },
        {"id": "output", "kind": "output", "component": "output.evidence"},
    ]
    edges += [
        {"source": "calibrate", "target": "policy"},
        {"source": "policy", "target": "output"},
    ]
    return PipelineDefinition.model_validate(
        {
            "schema_version": 2,
            "input_slots": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "nodes": nodes,
            "edges": edges,
            "settings": {
                "training_window_size": TRAINING,
                "calibration_window_size": calibration_window,
                "seed": 7,
            },
        }
    )
