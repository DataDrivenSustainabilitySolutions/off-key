"""Lane-free designs with a pretrained forecaster, run end to end.

Timestral scores reading a against the forecast service's forecasts, alone
or beside detectors that learn every observation or are fitted once, under
the fixed split or under a calibration step that keeps adapting.
"""

import math

import pytest
from off_key_core.models.adaptive import TIMESTRAL
from off_key_core.models.pipelines import derive_monitoring_config, validate_pipeline
from off_key_core.schemas.pipelines import PipelineDefinition
from off_key_mqtt_radar.adaptive_detector import (
    AdaptiveStreamDetectionService,
    AdaptiveStreamState,
)
from off_key_mqtt_radar.boundary_detector import BoundaryDetectionService
from off_key_mqtt_radar.detector_services import detector_service_class
from off_key_mqtt_radar.execution_errors import ObservationRejected
from off_key_mqtt_radar.mixed_detector import MixedDetectionService
from off_key_mqtt_radar.preflight import preflight

from tests.support import forecast_service
from tests.support.fused_pipeline import bound, reading

TRAINING, CALIBRATION = 30, 20
LEARNED = TRAINING + CALIBRATION
# Reading b into a detector that learns every observation, or one fitted once.
COMPANIONS = {
    "mad": (
        "adaptive.standard_scaler",
        "detector:aberrant_moving_average_absolute_deviation",
        {"window_size": 10},
    ),
    "knn": ("static.standard_scaler", "detector:pyod_knn", {}),
}
FIXED = ("calibrate.fixed_split", "policy.quantile")
ADAPTING = ("calibrate.aci", "policy.exceedance")


def definition(companions=(), steps=FIXED, lead=1) -> PipelineDefinition:
    """Timestral on reading a, each companion on reading b, one calibration step."""
    calibration, policy = steps
    nodes = [
        {"id": "input", "kind": "source", "component": "source.aligned"},
        {
            "id": "only_a",
            "kind": "transform",
            "component": "features.select",
            "params": {"features": ["a"]},
        },
        {
            "id": "timestral",
            "kind": "detector",
            "component": TIMESTRAL,
            "params": {"context_length": 32, "minimum_context": 16, "lead": lead},
        },
    ]
    edges = [
        {"source": "input", "target": "only_a"},
        {"source": "only_a", "target": "timestral"},
        {"source": "timestral", "target": "calibrate", "order": 0},
    ]
    for order, name in enumerate(companions, start=1):
        scaler, component, params = COMPANIONS[name]
        nodes += [
            {
                "id": f"only_b_{name}",
                "kind": "transform",
                "component": "features.select",
                "params": {"features": ["b"]},
            },
            {"id": f"scale_{name}", "kind": "transform", "component": scaler},
            {"id": name, "kind": "detector", "component": component, "params": params},
        ]
        edges += [
            {"source": "input", "target": f"only_b_{name}"},
            {"source": f"only_b_{name}", "target": f"scale_{name}"},
            {"source": f"scale_{name}", "target": name},
            {"source": name, "target": "calibrate", "order": order},
        ]
    nodes += [
        {
            "id": "calibrate",
            "kind": "calibration",
            "component": calibration,
            "params": {"alpha": 0.1} if steps is ADAPTING else {},
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
                "calibration_window_size": CALIBRATION,
                "seed": 7,
            },
        }
    )


def cycle(index):
    """Reading a repeats every four values; reading b is a slow wave."""
    return reading(100.0 + [0.0, 10.0, 0.0, -10.0][index % 4], math.cos(index / 7))


def feed(service, start, stop):
    results = []
    for index in range(start, stop):
        results.append(service.process_data_point(cycle(index)))
        service.wait_for_background()
    return results


SHAPES = [
    ((), FIXED, AdaptiveStreamDetectionService),
    (("mad",), FIXED, AdaptiveStreamDetectionService),
    (("knn",), FIXED, MixedDetectionService),
    ((), ADAPTING, BoundaryDetectionService),
    (("knn", "mad"), ADAPTING, BoundaryDetectionService),
]


@pytest.mark.parametrize(("companions", "steps", "service_class"), SHAPES)
def test_a_design_with_timestral_runs_and_alarms_on_a_break_in_the_cycle(
    monkeypatch, tmp_path, companions, steps, service_class
):
    calls = forecast_service.start(monkeypatch, tmp_path, season_length=4)["calls"]
    design = definition(companions, steps)
    assert validate_pipeline(design).valid
    assert derive_monitoring_config(design).strategy == "adaptive_stream"
    config = bound(design)
    assert detector_service_class(config) is service_class
    assert preflight(config.pipeline)["ok"] and calls == []

    service = service_class(config)
    try:
        results = feed(service, 0, LEARNED + 20)
        assert service.state == AdaptiveStreamState.OPERATIONAL
        if not companions:
            # The cycle is forecast exactly, so nothing alarms on it.
            assert not any(item.is_anomaly for item in results[LEARNED:])

        assert service.process_data_point(reading(110.0, math.cos(10.0))).is_anomaly
        # One request for the model, then a forecast with every value from the
        # sixteenth on.
        assert calls[0] == ("POST", "http://forecast/v1/downloads")
        assert len(calls) == 1 + (LEARNED + 21 - 15)
    finally:
        service.shutdown()


@pytest.mark.parametrize(("companions", "steps", "service_class"), SHAPES)
def test_an_outage_rejects_observations_whatever_runs_beside_timestral(
    monkeypatch, tmp_path, companions, steps, service_class
):
    state = forecast_service.start(monkeypatch, tmp_path, season_length=4)
    service = service_class(bound(definition(companions, steps)))
    try:
        feed(service, 0, LEARNED + 8)
        # The value before the outage still has its forecast; the next has none.
        monkeypatch.setitem(state, "down", True)
        service.process_data_point(cycle(LEARNED + 8))
        with pytest.raises(ObservationRejected, match="No forecast to compare with"):
            service.process_data_point(cycle(LEARNED + 9))
        assert service.state == AdaptiveStreamState.OPERATIONAL

        monkeypatch.setitem(state, "down", False)
        assert service.process_data_point(reading(110.0, 0.0)).is_anomaly
    finally:
        service.shutdown()
