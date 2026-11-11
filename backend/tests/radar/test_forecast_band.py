"""What a forecaster step expected of an observation, and the band around it.

A result names the forecast an observation was scored against. Where a
boundary applies to the step's own score, it also carries the calibrated
interval: a value outside it is above the boundary.
"""

from dataclasses import replace

import pytest
from off_key_core.models.pipeline_catalog import pipeline_catalog
from off_key_core.models.pipelines import validate_pipeline
from off_key_core.schemas.pipelines import PipelineDefinition
from off_key_mqtt_radar.boundary_detector import BoundaryDetectionService
from off_key_mqtt_radar.detector_services import detector_service_class
from off_key_mqtt_radar.result_records import ResultProjector

from tests.support.fused_pipeline import KEYS, bound, reading

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


def run(definition, steps: int = 30):
    """The scored results of a run, and the result of a break in the cycle."""
    service = detector_service_class(bound(definition))(bound(definition))
    try:
        results = []
        for index in range(LEARNED + steps):
            results.append(service.process_data_point(reading(cycle(index), 1.0)))
            service.wait_for_background()
        # The value arrives where the cycle expects its trough.
        last = LEARNED + steps
        spike = service.process_data_point(reading(cycle(last) + 40.0, 1.0))
        return service, results, spike
    finally:
        service.shutdown()


def forecasts(result):
    return result.context["adaptive_stream"].get("forecasts")


def test_forecaster_steps_hand_forecasts_to_the_calibration_step():
    components = {item.id: item for item in pipeline_catalog(True).components}

    assert components[FORECASTER].output_type == "forecasts"
    assert components["forecast.timestral"].output_type == "forecasts"
    assert components[MAD].output_type == "scores"
    for definition in (design(), design(calibration="calibrate.fixed_split")):
        assert validate_pipeline(definition).valid
    # Only a calibration step reads forecasts.
    straight = design().model_dump(mode="json")
    straight["edges"] = [
        edge for edge in straight["edges"] if edge["target"] != "calibrate"
    ] + [{"source": "forecaster", "target": "policy"}]
    report = validate_pipeline(PipelineDefinition.model_validate(straight))
    assert "Cannot connect forecasts to p_values" in [
        issue.message for issue in report.issues
    ]


@pytest.mark.parametrize("score", ["scaled", "absolute"])
@pytest.mark.parametrize("calibration", ["calibrate.aci", "calibrate.fixed_split"])
def test_a_result_carries_what_was_expected_and_the_calibrated_band(calibration, score):
    definition = design(calibration=calibration, score=score)
    service, results, spike = run(definition)

    assert isinstance(service, BoundaryDetectionService) == (
        calibration == "calibrate.aci"
    )
    # Nothing is expected of an observation that is not scored against a boundary.
    assert all(forecasts(item) is None for item in results[:LEARNED])
    for index, result in enumerate([*results[LEARNED:], spike], start=LEARNED):
        (entry,) = forecasts(result)
        context = result.context["adaptive_stream"]
        value = result.raw_data[KEYS["a"]]
        assert entry["detector_id"] == "forecaster"
        assert (entry["target"], entry["slot"], entry["lead"]) == ("a", "a", 1)
        # The seasonal naive forecast is the value one cycle ago.
        if index < LEARNED + 30:
            assert entry["expected"] == pytest.approx(cycle(index - 4))
        assert entry["lower"] <= entry["expected"] <= entry["upper"]
        inside = entry["lower"] <= value <= entry["upper"]
        assert inside == (result.anomaly_score <= context["threshold"])
    (entry,) = forecasts(spike)
    assert spike.is_anomaly
    assert spike.raw_data[KEYS["a"]] > entry["upper"]


def test_combined_detectors_have_no_band_of_their_own():
    _, results, spike = run(design(beside=True))

    for result in [*results[LEARNED:], spike]:
        (entry,) = forecasts(result)
        assert entry["detector_id"] == "forecaster"
        assert entry["expected"] is not None
        assert entry["lower"] is None and entry["upper"] is None


def test_a_target_a_step_changed_names_no_reading():
    _, results, _ = run(design(scaled=True))

    (entry,) = forecasts(results[-1])
    assert entry["target"] == "a" and entry["slot"] is None
    assert entry["lower"] < entry["upper"]


def test_a_design_without_a_forecaster_reports_no_forecasts():
    definition = design(beside=True).model_dump(mode="json")
    gone = {"forecaster", "only_a"}
    definition["nodes"] = [
        node for node in definition["nodes"] if node["id"] not in gone
    ]
    definition["edges"] = [
        edge
        for edge in definition["edges"]
        if not gone & {edge["source"], edge["target"]}
    ]
    _, results, spike = run(PipelineDefinition.model_validate(definition))

    assert all(forecasts(item) is None for item in [*results, spike])


def evidence(result):
    """The evidence row of a result, which a chart reads the forecast from."""
    monitored = replace(
        result,
        topic="charger/CP-7/live-telemetry/a",
        charger_id="CP-7",
        context={
            **result.context,
            "alignment": {
                "aligned_vector": True,
                "required_sensors": list(KEYS.values()),
                "input_timestamps": dict.fromkeys(
                    KEYS.values(), "2026-11-10T10:00:00Z"
                ),
            },
        },
    )
    (record,) = ResultProjector("forecasts")._build_evidence_records([monitored])
    return record


def inputs_of(record, detector_id):
    """The inputs a row stores for a detector; one detector is stored unnamed."""
    stored = {item["detector_id"]: item["inputs"] for item in record["detector_inputs"]}
    return stored.get(detector_id, stored.get(None))


@pytest.mark.parametrize("calibration", ["calibrate.aci", "calibrate.fixed_split"])
def test_the_evidence_of_a_run_keeps_the_forecast_and_its_band(calibration):
    _, results, spike = run(design(calibration=calibration))

    for result in (results[-1], spike):
        record = evidence(result)
        (stored,) = record["forecasts"]
        assert stored == result.context["adaptive_stream"]["forecasts"][0]
        assert stored["lower"] <= stored["expected"] <= stored["upper"]
        # The forecast is of a feature the row stores for the same detector.
        value = inputs_of(record, stored["detector_id"])[stored["target"]]
        assert (value > stored["upper"]) == record["alarm"]
    assert evidence(spike)["alarm"]


def test_combined_detectors_store_the_forecast_without_a_band():
    _, results, _ = run(design(beside=True))

    record = evidence(results[-1])
    (stored,) = record["forecasts"]
    assert stored["detector_id"] == "forecaster"
    assert stored["lower"] is None and stored["upper"] is None
    assert stored["target"] in inputs_of(record, "forecaster")


def test_a_forecast_of_a_changed_feature_is_stored_in_the_feature_s_units():
    _, results, _ = run(design(scaled=True))

    record = evidence(results[-1])
    (stored,) = record["forecasts"]
    scaled = inputs_of(record, stored["detector_id"])[stored["target"]]
    assert stored["slot"] is None
    # The band is around the scaled value the step scored, not the raw reading.
    assert stored["lower"] <= scaled <= stored["upper"]
    assert scaled != results[-1].raw_data[KEYS["a"]]
