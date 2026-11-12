"""Designs with a rule detector, for compiler and runtime tests."""

from __future__ import annotations

from off_key_core.schemas.pipeline_versions import RULE_DETECTOR
from off_key_core.schemas.pipelines import PipelineDefinition

from tests.support.boundary_pipeline import BRANCHES

TRAINING, CALIBRATION = 30, 20
# How far reading a is from reading b, as the one feature the rule scores.
GAP = "abs(a - b)"


def rule_definition(
    others: tuple[str, ...] = (),
    *,
    expression: str = GAP,
    policy: str = "policy.quantile",
    calibration: str = "calibrate.fixed_split",
    calibration_params: dict | None = None,
    before: str | None = None,
    rule: str = RULE_DETECTOR,
    rule_params: dict | None = None,
    calibration_window: int = CALIBRATION,
) -> PipelineDefinition:
    """A formula over readings a and b feeds a rule detector.

    ``others`` adds detectors from the boundary designs' branches beside it,
    each reading one scaled reading. ``before`` puts a step between the
    formula and the rule detector, and ``rule`` puts another detector in the
    rule detector's place.
    """
    nodes = [
        {"id": "input", "kind": "source", "component": "source.aligned"},
        {
            "id": "gap",
            "kind": "transform",
            "component": "prepare.formula",
            "params": {"expression": expression, "name": "gap", "result": "replace"},
        },
        {
            "id": "rule",
            "kind": "detector",
            "component": rule,
            "params": rule_params or {},
        },
    ]
    edges = [
        {"source": "input", "target": "gap"},
        {"source": "rule", "target": "calibrate", "order": 0},
    ]
    reads = "gap"
    if before is not None:
        nodes.append({"id": "before", "kind": "transform", "component": before})
        edges.append({"source": "gap", "target": "before"})
        reads = "before"
    edges.append({"source": reads, "target": "rule"})
    for order, name in enumerate(others, start=1):
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
            "params": calibration_params or {},
        },
        {"id": "policy", "kind": "policy", "component": policy},
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
