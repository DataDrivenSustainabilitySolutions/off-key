"""Lane-free designs with a pretrained forecaster, run end to end.

Timestral scores reading a against the forecast service's forecasts, alone
or beside detectors that learn every observation or are fitted once, under
the fixed split or under a calibration step that keeps adapting.
"""

import math
from datetime import UTC, datetime

import pytest
from off_key_core.models.adaptive import TIMESTRAL
from off_key_core.models.dojo_runs import BoundSeries, bind_dataset, series_topic
from off_key_core.models.pipelines import (
    compile_pipeline,
    derive_monitoring_config,
    validate_pipeline,
)
from off_key_core.schemas.dojo import RunAlignment
from off_key_core.schemas.pipelines import PipelineDefinition
from off_key_mqtt_radar.adaptive_detector import (
    AdaptiveStreamDetectionService,
    AdaptiveStreamState,
)
from off_key_mqtt_radar.boundary_detector import BoundaryDetectionService
from off_key_mqtt_radar.detector_services import detector_service_class
from off_key_mqtt_radar.dojo.replay import Replay, detection_config
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
        # Five values are rejected, so a gap would shift the cycle of four.
        for index in range(LEARNED + 9, LEARNED + 14):
            with pytest.raises(
                ObservationRejected, match="No forecast to compare with"
            ):
                service.process_data_point(cycle(index))
        assert service.state == AdaptiveStreamState.OPERATIONAL

        # The run did not learn them, but Timestral's series has no gap, so
        # the cycle is forecast as before.
        monkeypatch.setitem(state, "down", False)
        results = feed(service, LEARNED + 14, LEARNED + 26)
        if not companions:
            assert not any(item.is_anomaly for item in results)
            assert {item.anomaly_score for item in results} == {0.0}
        assert service.process_data_point(reading(110.0, 0.0)).is_anomaly
    finally:
        service.shutdown()


@pytest.mark.parametrize(("companions", "steps"), [((), FIXED), (("knn",), ADAPTING)])
def test_a_dojo_replay_scores_a_recording_against_timestral(
    monkeypatch, tmp_path, companions, steps
):
    calls = forecast_service.start(monkeypatch, tmp_path, season_length=4)["calls"]
    design = compile_pipeline(definition(companions, steps)).definition
    execution = bind_dataset(
        design,
        {
            slot.id: BoundSeries(
                id=f"series-{index}", position=index, name=slot.id, unit=None
            )
            for index, slot in enumerate(design.input_slots)
        },
        run_id="run",
    )
    start = datetime(2026, 3, 1, tzinfo=UTC).timestamp()

    def replayed():
        run = Replay(detection_config(execution, RunAlignment(), 16384))
        rows = []
        try:
            for index in range(LEARNED + 30):
                values = list(cycle(index).values())
                if index == LEARNED + 20:
                    values[0] = 110.0
                for slot, value in enumerate(values):
                    row = run.step(series_topic(slot), start + 60 * index, value)
                    if row is not None:
                        rows.append(row)
        finally:
            run.close()
        return rows

    rows = replayed()
    assert [row.sequence for row in rows] == list(range(1, LEARNED + 31))
    assert rows[LEARNED + 20].alarm
    # The weights are frozen, so a second replay gives the same rows.
    forecasts = len(calls)
    assert replayed() == rows and len(calls) == 2 * forecasts
