"""A forecaster step's design and the cycle it learns, shared by the forecast tests."""

from off_key_core.schemas.pipelines import PipelineDefinition

TRAINING, CALIBRATION = 16, 12
LEARNED = TRAINING + CALIBRATION
CYCLE = [0.0, 10.0, 0.0, -10.0]
FORECASTER = "detector:aberrant_seasonal_naive_forecaster"
MAD = "detector:aberrant_moving_average_absolute_deviation"


def design(
    *,
    calibration: str = "calibrate.aci",
    scaled: bool = False,
    beside: bool = False,
    score: str = "scaled",
    lead: int = 1,
    smooth: bool = False,
) -> PipelineDefinition:
    """Reading a through a forecaster step into one calibration step."""
    adapts = calibration != "calibrate.fixed_split"
    nodes = [
        {"id": "input", "kind": "source", "component": "source.aligned"},
        {
            "id": "only_a",
            "kind": "transform",
            "component": "features.select",
            "params": {"features": ["a"]},
        },
        {
            "id": "forecaster",
            "kind": "detector",
            "component": FORECASTER,
            "params": {"season_length": 4, "score": score, "lead": lead},
        },
        {
            "id": "calibrate",
            "kind": "calibration",
            "component": calibration,
            "params": {"alpha": 0.1} if adapts else {},
        },
        {
            "id": "policy",
            "kind": "policy",
            "component": "policy.exceedance" if adapts else "policy.quantile",
        },
        {"id": "output", "kind": "output", "component": "output.evidence"},
    ]
    edges = [
        {"source": "input", "target": "only_a"},
        {"source": "forecaster", "target": "calibrate", "order": 0},
        {"source": "calibrate", "target": "policy"},
        {"source": "policy", "target": "output"},
    ]
    source = "only_a"
    if smooth:
        nodes.append(
            {
                "id": "smooth",
                "kind": "transform",
                "component": "prepare.smooth",
                "params": {"method": "rolling", "window_size": 3},
            }
        )
        edges.append({"source": source, "target": "smooth"})
        source = "smooth"
    if scaled:
        nodes.append(
            {
                "id": "scale",
                "kind": "transform",
                "component": "adaptive.standard_scaler",
            }
        )
        edges.append({"source": source, "target": "scale"})
        source = "scale"
    edges.append({"source": source, "target": "forecaster"})
    if beside:
        nodes += [
            {
                "id": "only_b",
                "kind": "transform",
                "component": "features.select",
                "params": {"features": ["b"]},
            },
            {
                "id": "mad",
                "kind": "detector",
                "component": MAD,
                "params": {"window_size": 10},
            },
        ]
        edges += [
            {"source": "input", "target": "only_b"},
            {"source": "only_b", "target": "mad"},
            {"source": "mad", "target": "calibrate", "order": 1},
        ]
    return PipelineDefinition.model_validate(
        {
            "schema_version": 2,
            "input_slots": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "nodes": nodes,
            "edges": edges,
            "settings": {
                "training_window_size": TRAINING,
                "calibration_window_size": CALIBRATION,
                "seed": 7,
            },
        }
    )


def cycle(index: int) -> float:
    # A little drift, so the forecasts miss by something a boundary can learn.
    return 100.0 + CYCLE[index % 4] + 0.3 * ((index * 7) % 5)
