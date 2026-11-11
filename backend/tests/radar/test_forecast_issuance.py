"""Future evidence uses issued predictions, their own lead and causal timing."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from aberrant.base.forecast import Forecast
from aberrant.forecast import ResidualDetector, SeasonalNaive
from aberrant.forecast.scores import interval
from off_key_mqtt_radar.detector_services import detector_service_class
from off_key_mqtt_radar.forecast_issuance import ForecastTimeline, issued_forecast
from off_key_mqtt_radar.forecast_records import (
    MAX_ISSUED_POINTS,
    normalize_issued_forecast,
)
from off_key_mqtt_radar.result_records import ResultProjector

from tests.radar.test_forecast_band import LEARNED, cycle, design
from tests.support.fused_pipeline import KEYS, bound, reading

START = datetime(2026, 11, 11, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    "calibration", ["calibrate.nexcp", "calibrate.aci", "calibrate.fixed_split"]
)
@pytest.mark.parametrize("smooth", [False, True])
def test_issued_trajectory_survives_runtime_timing_and_storage(calibration, smooth):
    config = bound(design(calibration=calibration, lead=3, smooth=smooth))
    service = detector_service_class(config)(config)
    projector = ResultProjector("forecast")
    try:
        for index in range(LEARNED + 12):
            result = service.process_data_point(reading(cycle(index), 1.0))
            service.wait_for_background()
            timestamp = START + timedelta(seconds=index)
            # Raw targets use their own sensor's time; transformed targets use
            # the aligned observation's time, even when the input clocks differ.
            times = {
                KEYS["a"]: timestamp,
                KEYS["b"]: timestamp + timedelta(milliseconds=200),
            }
            service.attach_observation_metadata(max(times.values()), times)
        (entry,) = result.context["adaptive_stream"]["forecasts"]
        issued = entry["issued"]
        current = service.pipeline.model._issued[-1]
        assert issued["origin_step"] == current.origin
        assert issued["time_basis"] == "estimated_cadence"
        assert issued["step_seconds"] == 1
        origin = timestamp + timedelta(milliseconds=200 if smooth else 0)
        assert issued["origin_time"] == origin.isoformat()
        assert [point["expected"] for point in issued["points"]] == list(current.mean)
        assert [point["target_time"] for point in issued["points"]] == [
            (origin + timedelta(seconds=lead)).isoformat() for lead in (1, 2, 3)
        ]
        assert all(point["lower"] is None for point in issued["points"][:-1])
        threshold = (
            service.boundary.next_threshold()
            if hasattr(service, "boundary")
            else service.threshold
        )
        last = issued["points"][-1]
        assert (last["lower"], last["upper"]) == interval(
            current, 3, threshold, service.pipeline.model.score
        )
        result.context["alignment"] = {
            "aligned_vector": True,
            "required_sensors": list(KEYS.values()),
            "input_timestamps": times,
        }
        (record,) = projector._build_evidence_records([result])
        assert record["forecasts"][0]["issued"] == issued
        observed = result.processed_features["a"]
        assert (observed != result.raw_data[KEYS["a"]]) == smooth
    finally:
        service.shutdown()


def test_evidence_does_not_request_another_forecast_or_use_an_older_origin(monkeypatch):
    detector = ResidualDetector(SeasonalNaive(season_length=2, horizon=3), "x", lead=3)
    for value in range(12):
        detector.learn_one({"x": float(value)})

    def no_inference():
        raise AssertionError("Evidence must not trigger inference")

    monkeypatch.setattr(detector.model, "forecast_one", no_inference)
    issued = issued_forecast(detector, 2)
    assert issued["origin_step"] == detector._issued[-1].origin
    assert issued["origin_step"] != detector.forecast_for({"x": 12}).origin
    detector._issued.append(None)
    assert issued_forecast(detector, 2) is None


def test_long_horizons_store_bounded_real_points_including_the_calibrated_lead():
    detector = ResidualDetector(
        SeasonalNaive(season_length=2, horizon=1024), "x", lead=511
    )
    detector._issued.append(
        Forecast(
            origin=100,
            leads=tuple(range(1, 1025)),
            mean=tuple(range(1, 1025)),
            scale=(1.0,) * 1024,
        )
    )
    issued = issued_forecast(detector, 2)
    leads = [point["lead"] for point in issued["points"]]
    assert len(leads) <= MAX_ISSUED_POINTS
    assert {1, 511, 1024}.issubset(leads)
    assert all(point["expected"] == point["lead"] for point in issued["points"])
    assert [
        point["lead"] for point in issued["points"] if point["lower"] is not None
    ] == [511]


def test_timing_needs_consecutive_cadence_and_clears_after_a_gap_or_restart():
    timeline = ForecastTimeline()
    plan = SimpleNamespace(execution=SimpleNamespace(bindings=[]))

    def stamp(step, seconds):
        issued = {
            "origin_step": step,
            "origin_time": None,
            "time_basis": "unavailable",
            "step_seconds": None,
            "points": [{"lead": 2, "target_time": None}],
        }
        entry = {"detector_id": "model", "slot": None, "issued": issued}
        timeline.stamp([entry], plan, START + timedelta(seconds=seconds), {})
        return issued

    for step in range(3):
        assert stamp(step, step)["time_basis"] == "unavailable"
    good = stamp(3, 3)
    assert (
        good["points"][0]["target_time"] == (START + timedelta(seconds=5)).isoformat()
    )
    assert stamp(4, 60)["time_basis"] == "unavailable"
    assert stamp(5, 60)["time_basis"] == "unavailable"
    assert stamp(0, 61)["time_basis"] == "unavailable"


def test_normalization_drops_invalid_bounds_and_times_without_losing_points():
    issued = {
        "issued_at": START.isoformat(),
        "origin_step": 5,
        "origin_time": START.isoformat(),
        "time_basis": "estimated_cadence",
        "step_seconds": 1,
        "points": [
            {
                "lead": lead,
                "target_time": (START + timedelta(seconds=lead)).isoformat(),
                "expected": 10.0,
                "lower": 9.0,
                "upper": 11.0,
            }
            for lead in (1, 2, 3)
        ],
    }
    bad = deepcopy(issued)
    bad["points"][1]["target_time"] = START.isoformat()
    bad["points"][2]["upper"] = float("nan")
    normalized = normalize_issued_forecast(bad, 3)
    assert len(normalized["points"]) == 3
    assert normalized["points"][1]["target_time"] is None
    assert all(
        point["lower"] is None and point["upper"] is None
        for point in normalized["points"]
    )
    assert normalize_issued_forecast({**issued, "issued_at": "bad"}, 3) is None
