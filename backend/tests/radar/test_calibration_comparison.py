"""Other calibration methods tried on a replay's own detector scores.

A compared method must alarm exactly where a run with that calibration step
would, so a comparison can stand in for running the design once per method.
"""

import math

import pytest
from off_key_core.models.dojo_runs import (
    FIXED_METHOD,
    BoundSeries,
    bind_dataset,
    calibration_comparison,
    series_topic,
)
from off_key_core.models.pipeline_calibration import CALIBRATORS
from off_key_core.models.pipelines import compile_pipeline
from off_key_core.schemas.dojo import RunAlignment
from off_key_mqtt_radar.calibration_comparison import CalibrationComparison
from off_key_mqtt_radar.detector_services import detector_service_class
from off_key_mqtt_radar.dojo.replay import Replay, detection_config
from off_key_mqtt_radar.pipelines.plan import ExecutionPlan

from tests.support.boundary_pipeline import CALIBRATION, TRAINING, boundary_definition
from tests.support.fused_pipeline import bound

LEARNED = TRAINING + CALIBRATION
START = 1_700_000_000.0
# Far above a test process, so the replay does not collect garbage per message.
MEMORY_LIMIT_MB = 16384
SHAPES = [("mad",), ("knn", "mad")]


def fixed(detectors, quantile=0.9):
    return boundary_definition(
        detectors,
        calibration="calibrate.fixed_split",
        params={},
        policy="policy.quantile",
        policy_params={"quantile": quantile},
    )


def adapting(detectors, method="aci", consecutive=1):
    return boundary_definition(
        detectors,
        calibration=f"calibrate.{method}",
        policy_params={"consecutive": consecutive},
    )


def execution(definition):
    definition = compile_pipeline(definition).definition
    return bind_dataset(
        definition,
        {
            slot.id: BoundSeries(
                id=f"series-{index}", position=index, name=slot.id, unit=None
            )
            for index, slot in enumerate(definition.input_slots)
        },
        run_id="run",
    )


def plan_of(definition):
    return ExecutionPlan(execution(definition))


def signal(index):
    """A wave with a few bursts, so boundaries are crossed now and then."""
    burst = 6.0 if index % 37 in (0, 1, 2) and index > LEARNED else 0.0
    return math.sin(index / 5) + burst, math.cos(index / 7) + burst


def replayed(definition, *, compare, steps=LEARNED + 220):
    """Every result of a replay of `definition` over the signal."""
    comparison = (
        calibration_comparison(compile_pipeline(definition)) if compare else None
    )
    run = Replay(
        detection_config(execution(definition), RunAlignment(), MEMORY_LIMIT_MB),
        comparison,
    )
    rows = []
    try:
        for index in range(steps):
            for slot, value in enumerate(signal(index)):
                row = run.step(series_topic(slot), START + index, value)
                if row is not None:
                    rows.append(row)
    finally:
        run.close()
    return rows, comparison, run


def bits(rows, comparison, method):
    bit = 1 << comparison["methods"].index(method)
    return [bool(row.method_alarms & bit) for row in rows if row.phase == "operational"]


def alarms(rows):
    return [row.alarm for row in rows if row.phase == "operational"]


def test_a_design_names_the_methods_it_can_be_compared_with():
    threshold = calibration_comparison(compile_pipeline(fixed(("mad",))))
    assert threshold["own"] == FIXED_METHOD
    assert threshold["methods"] == list(CALIBRATORS)
    assert threshold["alpha"] == pytest.approx(0.1)
    assert threshold["consecutive"] == 1

    boundary = calibration_comparison(compile_pipeline(adapting(("mad",), "pid", 3)))
    assert boundary["own"] == "pid"
    assert boundary["methods"] == [
        FIXED_METHOD,
        *(method for method in CALIBRATORS if method != "pid"),
    ]
    assert (boundary["alpha"], boundary["consecutive"]) == (0.1, 3)

    # The largest calibration score leaves one score in n + 1 above it.
    largest = calibration_comparison(compile_pipeline(fixed(("mad",), quantile=1.0)))
    assert largest["alpha"] == pytest.approx(1 / (CALIBRATION + 1))

    # Detectors fitted once under a fixed split alarm on a martingale.
    martingale = boundary_definition(
        ("knn",),
        calibration="calibrate.fixed_split",
        params={},
        policy="policy.martingale",
    )
    assert calibration_comparison(compile_pipeline(martingale)) is None


@pytest.mark.parametrize("detectors", SHAPES)
def test_a_compared_method_alarms_where_a_run_with_that_step_would(detectors):
    threshold_rows, comparison, _ = replayed(fixed(detectors), compare=True)
    boundary_rows, _, _ = replayed(adapting(detectors), compare=False)

    compared = bits(threshold_rows, comparison, "aci")
    assert compared == alarms(boundary_rows)
    # The signal crosses the boundary, and not on every observation.
    assert 0 < sum(compared) < len(compared)
    # Nothing is judged before the run itself is.
    assert all(
        row.method_alarms is None
        for row in threshold_rows
        if row.phase != "operational"
    )
    assert all(row.method_alarms is None for row in boundary_rows)


@pytest.mark.parametrize("detectors", SHAPES)
def test_the_compared_fixed_split_alarms_where_a_fixed_split_run_would(detectors):
    boundary_rows, comparison, _ = replayed(adapting(detectors), compare=True)
    threshold_rows, _, _ = replayed(fixed(detectors), compare=False)

    compared = bits(boundary_rows, comparison, FIXED_METHOD)
    assert compared == alarms(threshold_rows)
    assert 0 < sum(compared) < len(compared)


def test_comparing_changes_nothing_about_the_run_itself():
    plain, _, _ = replayed(adapting(("knn", "mad")), compare=False)
    compared, _, _ = replayed(adapting(("knn", "mad")), compare=True)

    assert [(row.score, row.threshold, row.alarm) for row in plain] == [
        (row.score, row.threshold, row.alarm) for row in compared
    ]


def test_every_method_runs_on_the_scores_of_one_replay():
    rows, comparison, run = replayed(fixed(("mad",)), compare=True)

    assert run.comparison.failed == {}
    assert len(comparison["methods"]) == 15
    judged = [row.method_alarms for row in rows if row.phase == "operational"]
    assert len(judged) == 220
    # Each method alarms somewhere on the bursts.
    for position in range(15):
        assert any(mask >> position & 1 for mask in judged), comparison["methods"][
            position
        ]


def test_an_alarm_waits_for_enough_exceedances_in_a_row():
    comparison = CalibrationComparison(
        plan_of(fixed(("mad",))), [FIXED_METHOD], alpha=0.1, consecutive=2
    )
    comparison.start([[float(score)] for score in range(CALIBRATION)])

    # 18 is the 0.9 quantile of 0 to 19; a score has to be above it.
    assert [comparison.observe([score]) for score in (18, 19, 19, 5, 19)] == [
        0,
        0,
        1,
        0,
        0,
    ]


def test_a_method_that_fails_leaves_and_the_others_carry_on(monkeypatch):
    comparison = CalibrationComparison(
        plan_of(fixed(("mad",))),
        ["aci", FIXED_METHOD, "split"],
        alpha=0.1,
        consecutive=1,
    )
    comparison.start([[float(score)] for score in range(CALIBRATION)])
    assert comparison.observe([100.0]) == 0b111

    def broken(key, score):
        raise ArithmeticError("no more")

    monkeypatch.setattr(comparison._boundaries[0].calibrator, "update", broken)
    assert comparison.observe([200.0]) == 0b110
    assert comparison.observe([300.0]) == 0b110
    assert comparison.failed == {"aci": "ArithmeticError: no more"}


def test_only_a_boundary_on_scores_can_be_compared():
    martingale = boundary_definition(
        ("knn",),
        calibration="calibrate.fixed_split",
        params={},
        policy="policy.martingale",
    )
    assert detector_service_class(bound(martingale)).__name__ == (
        "StaticConformalDetectionService"
    )
    config = detection_config(execution(martingale), RunAlignment(), MEMORY_LIMIT_MB)
    with pytest.raises(ValueError, match="Only a boundary on scores"):
        Replay(config, {"methods": ["aci"], "alpha": 0.1, "consecutive": 1})
