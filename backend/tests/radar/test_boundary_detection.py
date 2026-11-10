"""Runs whose calibration step keeps adapting a boundary on the scores.

The calibration window seeds a method from aberrant.calibration, every scored
observation updates it, and the exceedance rule alarms above it. Detectors
fitted once, detectors that learn every observation and both together run
under it.
"""

import math
import pickle
from datetime import UTC, datetime

import pytest
from off_key_core.models.dojo_runs import BoundSeries, bind_dataset, series_topic
from off_key_core.models.pipeline_calibration import CALIBRATORS
from off_key_core.models.pipelines import compile_pipeline, derive_monitoring_config
from off_key_core.schemas.dojo import RunAlignment
from off_key_core.schemas.radar import AdaptiveStreamConfig, StaticBaselineConfig
from off_key_mqtt_radar.adaptive_detector import AdaptiveStreamState
from off_key_mqtt_radar.boundary import ScoreBoundary
from off_key_mqtt_radar.boundary_detector import BoundaryDetectionService
from off_key_mqtt_radar.detector_services import detector_service_class
from off_key_mqtt_radar.dojo.replay import Replay, detection_config
from off_key_mqtt_radar.fusion import RankFusion, RollingRanks
from off_key_mqtt_radar.health_monitor import HealthMonitor
from off_key_mqtt_radar.pipelines.plan import ExecutionPlan
from off_key_mqtt_radar.pipelines.resources import estimate_resources
from off_key_mqtt_radar.preflight import preflight

from tests.support.boundary_pipeline import CALIBRATION, TRAINING, boundary_definition
from tests.support.fused_pipeline import bound, reading

LEARNED = TRAINING + CALIBRATION
SHAPES = [("knn", "mad"), ("mad",), ("knn",)]


def wave(index):
    return reading(math.sin(index / 5), math.cos(index / 7))


def feed(service, start, stop):
    results = []
    for index in range(start, stop):
        results.append(service.process_data_point(wave(index)))
        service.wait_for_background()
    return results


def outcomes(results):
    return [
        (
            item.anomaly_score,
            item.context["adaptive_stream"]["threshold"],
            item.is_anomaly,
        )
        for item in results
    ]


@pytest.mark.parametrize(
    ("detectors", "settings", "model_type"),
    [
        (
            ("knn", "mad"),
            AdaptiveStreamConfig,
            "aberrant_moving_average_absolute_deviation",
        ),
        (("mad",), AdaptiveStreamConfig, "aberrant_moving_average_absolute_deviation"),
        (("knn",), StaticBaselineConfig, "pyod_knn"),
    ],
)
def test_any_detectors_run_under_an_adapting_boundary(detectors, settings, model_type):
    definition = boundary_definition(detectors)

    monitoring = derive_monitoring_config(definition)
    assert isinstance(monitoring, settings)
    assert monitoring.model_type == model_type
    assert detector_service_class(bound(definition)) is BoundaryDetectionService


@pytest.mark.parametrize("detectors", SHAPES)
def test_the_run_learns_calibrates_and_alarms_on_a_spike(detectors):
    service = BoundaryDetectionService(bound(boundary_definition(detectors)))
    try:
        results = feed(service, 0, LEARNED + 40)
        phases = [item.context["adaptive_stream"]["phase"] for item in results]
        assert phases[:TRAINING] == ["warmup"] * TRAINING
        assert phases[TRAINING:LEARNED] == ["calibration"] * CALIBRATION
        # The replay waited for the fit, so nothing was left unscored.
        assert set(phases[LEARNED:]) == {"operational"}
        assert service.state == AdaptiveStreamState.OPERATIONAL
        assert not service.calibration_scores and not service.batch.calibration
        # The boundary has seen the calibration window and every score since.
        assert service.boundary.key == CALIBRATION + 40

        spike = service.process_data_point(reading(40.0, 40.0))
        context = spike.context["adaptive_stream"]
        assert spike.is_anomaly and context["alarm_fired"]
        assert spike.anomaly_score > context["threshold"]
        assert ("detectors" in context) == (len(detectors) > 1)
        if len(detectors) > 1:
            assert {item["detector_id"] for item in context["detectors"]} == set(
                detectors
            )
            assert max(item["surprise"] for item in context["detectors"]) == 1.0
        info = service.get_model_info()
        assert info["strategy"] == "adaptive_stream"
        assert info["calibration"]["method"] == "aci"
        assert info["calibration"]["exceedances_in_a_row"] == 1
        state = service.get_pipeline_state()
        assert ("batch_training" in state) == ("knn" in detectors)
        assert ("adaptive_learning" in state) == ("mad" in detectors)
    finally:
        service.shutdown()


def test_the_boundary_follows_the_scores_where_a_fixed_split_stays():
    """A lasting shift raises the scores; the boundary catches up with them."""
    service = BoundaryDetectionService(
        bound(boundary_definition(("knn",), calibration="calibrate.split"))
    )
    try:
        feed(service, 0, LEARNED)
        shifted = [
            service.process_data_point(reading(5.0 + math.sin(index / 5), 0.0))
            for index in range(3 * CALIBRATION)
        ]
        before = shifted[0].context["adaptive_stream"]["threshold"]
        alarms = [item.is_anomaly for item in shifted]
        assert all(alarms[:3])
        # Once the window holds only shifted scores, they are the normal ones.
        assert not any(alarms[-CALIBRATION // 2 :])
        assert service.threshold > before
    finally:
        service.shutdown()


@pytest.mark.parametrize("method", sorted(CALIBRATORS))
def test_every_method_runs_and_holds_its_alarms_near_the_target(method):
    definition = boundary_definition(
        ("mad",), calibration=f"calibrate.{method}", calibration_window=60
    )
    service = BoundaryDetectionService(bound(definition))
    try:
        results = feed(service, 0, TRAINING + 60 + 400)[TRAINING + 60 :]
        thresholds = [item.context["adaptive_stream"]["threshold"] for item in results]
        assert all(math.isfinite(value) for value in thresholds)
        rate = sum(item.is_anomaly for item in results) / len(results)
        # Every method was asked for one alarm in ten.
        assert 0.02 <= rate <= 0.2
    finally:
        service.shutdown()


def test_the_rule_waits_for_exceedances_in_a_row():
    definition = boundary_definition(("knn",), policy_params={"consecutive": 3})
    service = BoundaryDetectionService(bound(definition))
    try:
        feed(service, 0, LEARNED + 20)
        while service.boundary.run:
            service.process_data_point(wave(0))
        before = service.anomaly_count
        # Each spike is further out than the last, so each is above a boundary
        # that already rose to the one before.
        spikes = [
            service.process_data_point(reading(40.0 * 2**step, 0.0))
            for step in range(4)
        ]
        for item in spikes:
            assert item.anomaly_score > item.context["adaptive_stream"]["threshold"]
        assert [item.is_anomaly for item in spikes] == [False, False, True, True]
        assert service.anomaly_count == before + 2
        assert service.boundary.run == 4
        service.process_data_point(wave(0))
        assert service.boundary.run == 0
    finally:
        service.shutdown()


def test_an_observation_a_detector_skips_does_not_move_the_boundary():
    service = BoundaryDetectionService(bound(boundary_definition(("knn", "mad"))))
    try:
        feed(service, 0, LEARNED + 5)
        key, run = service.boundary.key, service.boundary.run
        windows = [list(window) for window in service.boundary.ranks.windows]
        with pytest.raises(Exception, match="finite"):
            service.process_data_point(reading(float("nan"), 0.0))
        assert service.boundary.key == key and service.boundary.run == run
        assert [list(window) for window in service.boundary.ranks.windows] == windows
    finally:
        service.shutdown()


@pytest.mark.parametrize("detectors", SHAPES)
@pytest.mark.parametrize("stop", [TRAINING + 5, LEARNED, LEARNED + 7])
def test_a_checkpoint_continues_exactly_where_it_left_off(detectors, stop):
    config = bound(boundary_definition(detectors))
    original = BoundaryDetectionService(config)
    try:
        for index in range(stop):
            original.process_data_point(wave(index))
        # A checkpoint taken while fitting refits after the restore.
        restored = BoundaryDetectionService.from_checkpoint_data(
            pickle.loads(pickle.dumps(original.export_checkpoint())), config
        )
        try:
            original.wait_for_background()
            restored.wait_for_background()
            expected = outcomes(feed(original, stop, stop + 40))
            assert outcomes(feed(restored, stop, stop + 40)) == expected
            assert restored.boundary.run == original.boundary.run
        finally:
            restored.shutdown()
    finally:
        original.shutdown()


def test_a_checkpoint_of_another_calibration_step_is_refused():
    original = BoundaryDetectionService(bound(boundary_definition(("mad",))))
    for index in range(LEARNED + 3):
        original.process_data_point(wave(index))
    checkpoint = pickle.loads(pickle.dumps(original.export_checkpoint()))
    other = bound(boundary_definition(("mad",), params={"alpha": 0.2}))

    with pytest.raises(ValueError, match="incompatible"):
        BoundaryDetectionService.from_checkpoint_data(checkpoint, other)
    checkpoint["schema_signature"] = BoundaryDetectionService._build_schema_signature(
        other
    )
    with pytest.raises(ValueError, match="calibration step"):
        BoundaryDetectionService.from_checkpoint_data(checkpoint, other)


def test_ranks_roll_with_each_detectors_latest_scores():
    calibration = [[1.0, 10.0], [2.0, 30.0], [3.0, 20.0]]
    ranks = RollingRanks(calibration, "max")
    frozen = RankFusion(calibration, "max")

    assert ranks.seed == [frozen.value(count) for count in frozen.calibration_counts()]
    assert ranks.surprises([2.5, 5.0]) == [pytest.approx(2 / 3), 0.0]
    assert ranks.value([2 / 3, 0.0]) == pytest.approx(2 / 3)
    assert RollingRanks(calibration, "mean").value([2 / 3, 0.0]) == pytest.approx(2 / 6)
    ranks.push([2.5, 5.0])
    # The oldest score of each detector left: 1.0 and 10.0.
    assert [list(window) for window in ranks.windows] == [
        [2.0, 3.0, 2.5],
        [30.0, 20.0, 5.0],
    ]
    assert ranks.sorted == [[2.0, 2.5, 3.0], [5.0, 20.0, 30.0]]
    assert ranks.surprises([2.5, 25.0]) == [pytest.approx(1 / 3), pytest.approx(2 / 3)]


def test_a_score_above_its_whole_window_counts_for_how_far_above():
    ranks = RollingRanks([[1.0, 4.0], [2.0, 4.0], [3.0, 4.0]], "max")

    # The window's largest score has two of the three below it.
    assert ranks.surprises([3.0, 4.0]) == [pytest.approx(2 / 3), 0.0]
    just, far = ranks.surprises([3.02, 4.0])[0], ranks.surprises([7.0, 4.0])[0]
    assert just == pytest.approx(1.01) and far == pytest.approx(3.0)
    # A window of equal scores has no range, so its level is the unit.
    assert ranks.surprises([0.0, 6.0])[1] == pytest.approx(1.5)
    with pytest.raises(ValueError, match="Expected 2 detector scores"):
        ranks.surprises([1.0])


def test_a_boundary_at_the_top_rank_still_sees_a_larger_spike():
    """ACI can push its boundary to the largest value seen; ranks alone stop at 1."""
    service = BoundaryDetectionService(bound(boundary_definition(("forest", "mad"))))
    try:
        feed(service, 0, LEARNED + 20)
        boundary = service.boundary
        # Scores above every window, each further out, raise the boundary past 1.
        for step in range(1, 6):
            service.process_data_point(reading(0.0, 10.0 * step))
        assert boundary.next_threshold() >= 1.0
        spike = service.process_data_point(reading(0.0, 4000.0))
        assert spike.is_anomaly
        context = spike.context["adaptive_stream"]
        assert spike.anomaly_score > context["threshold"] >= 1.0
        shown = [item["surprise"] for item in context["detectors"]]
        assert max(shown) == 1.0
    finally:
        service.shutdown()


def test_the_boundary_issues_a_threshold_before_it_learns_the_score():
    plan = ExecutionPlan(
        bound(boundary_definition(("mad",), calibration="calibrate.split")).pipeline
    )
    boundary = ScoreBoundary(plan)
    with pytest.raises(RuntimeError, match="no calibration window"):
        boundary.judge([1.0])
    boundary.start([[float(value)] for value in range(CALIBRATION)])

    judgement = boundary.judge([100.0])
    # The 19th smallest of 0..19: ceil(21 * 0.9) scores are at or below it.
    assert judgement.threshold == 18.0 and judgement.alarm
    # Judging again changes nothing: the score is not learned yet.
    assert boundary.judge([100.0]) == judgement
    boundary.learn(judgement)
    with pytest.raises(RuntimeError, match="once, in order"):
        boundary.learn(judgement)
    # The window dropped 0 and took 100 in.
    assert boundary.judge([100.0]).threshold == 19.0


def test_preflight_sizing_and_health_cover_the_boundary():
    config = bound(boundary_definition(("knn", "mad")))
    report = preflight(config.pipeline)

    assert report["ok"] and set(report["capabilities"]) == {"mad"}
    plan = ExecutionPlan(config.pipeline)
    fixed = ExecutionPlan(
        bound(
            boundary_definition(
                ("knn", "mad"),
                calibration="calibrate.fixed_split",
                params={},
                policy="policy.quantile",
            )
        ).pipeline
    )
    assert (
        estimate_resources(plan, 512).fusion_state_bytes
        > estimate_resources(fixed, 512).fusion_state_bytes
    )
    assert preflight(bound(boundary_definition(("knn",))).pipeline)["ok"]
    service = BoundaryDetectionService(bound(boundary_definition(("knn",))))
    try:
        feed(service, 0, 3)
        stage, _, progress = HealthMonitor._running_stage(service.get_model_info())
        assert (stage, progress) == (
            "collecting_training",
            {"current": 3, "target": TRAINING},
        )
    finally:
        service.shutdown()


@pytest.mark.parametrize("detectors", [("forest", "mad"), ("knn",), ("mad",)])
def test_a_dojo_replay_runs_an_adapting_calibration_step_end_to_end(detectors):
    definition = compile_pipeline(boundary_definition(detectors)).definition
    execution = bind_dataset(
        definition,
        {
            slot.id: BoundSeries(
                id=f"series-{index}", position=index, name=slot.id, unit=None
            )
            for index, slot in enumerate(definition.input_slots)
        },
        run_id="run",
    )
    start = datetime(2026, 3, 1, tzinfo=UTC).timestamp()

    def replayed():
        run = Replay(detection_config(execution, RunAlignment(), 16384))
        rows = []
        try:
            for index in range(LEARNED + 30):
                values = list(wave(index).values())
                if index == LEARNED + 20:
                    values = [40.0, 40.0]
                for slot, value in enumerate(values):
                    row = run.step(series_topic(slot), start + 60 * index, value)
                    if row is not None:
                        rows.append(row)
        finally:
            run.close()
        return rows

    rows = replayed()
    assert [row.sequence for row in rows] == list(range(1, LEARNED + 31))
    assert {row.phase for row in rows[:LEARNED]} == {"warmup", "calibration"}
    scored = [row for row in rows if row.score is not None]
    # Every observation after the calibration window has a score and the
    # boundary it met, which moves with the scores.
    assert len(scored) == 30 and all(row.threshold is not None for row in scored)
    assert len({row.threshold for row in scored}) > 1
    assert rows[LEARNED + 20].alarm
    assert replayed() == rows
