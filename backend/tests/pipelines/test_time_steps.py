"""Steps that read when an observation was measured: Time features and a
Smooth by time constant."""

import math
import pickle
import random
import sys
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from off_key_core.models.dojo_runs import BoundSeries, bind_dataset, series_topic
from off_key_core.models.pipeline_prepare import (
    default_suffix,
    kernel,
    prepared_bounds,
    reads_time,
    step_lead,
)
from off_key_core.models.pipeline_reports import bounded_validation_report
from off_key_core.models.pipeline_time import (
    POSITIVE,
    TIME_FEATURES,
    Clock,
    TimeFeatures,
    time_names,
)
from off_key_core.models.pipelines import compile_pipeline, validate_pipeline
from off_key_core.schemas.dojo import RunAlignment
from off_key_core.schemas.pipelines import TIME_SETTINGS, TimeParameters
from off_key_mqtt_radar.adaptive_detector import AdaptiveStreamDetectionService
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig
from off_key_mqtt_radar.detector import StaticConformalDetectionService
from off_key_mqtt_radar.dojo.replay import Replay, detection_config
from off_key_mqtt_radar.pipelines import prepare as prepare_module
from off_key_mqtt_radar.pipelines.plan import ExecutionPlan
from off_key_mqtt_radar.pipelines.prepare import PrepareRejected, PrepareStage, Withheld
from off_key_mqtt_radar.pipelines.resources import estimate_resources

from tests.support.pipelines import chained, chained_execution

pytestmark = pytest.mark.radar_integration

BERLIN = ZoneInfo("Europe/Berlin")
# A Monday morning.
START = datetime(2026, 3, 2, 8, 0, tzinfo=UTC).timestamp()
CALENDAR = {"hour": True, "weekday": True, "daily_cycle": True, "weekly_cycle": True}
CLOCK = ("clock", "prepare.time", {})
ROW = {"a": 3.0, "b": 2.0}
# Per-second rate and energy, the daily pattern, and a level smoothed by time.
STEPS = [
    ("clock", "prepare.time", {"daily_cycle": True, "timezone": "Europe/Berlin"}),
    ("calc", "prepare.calculate", {"formulas": "rate = a / dt\nwork = b * dt"}),
    ("energy", "prepare.accumulate", {"apply_to": ["work"]}),
    (
        "calm",
        "prepare.smooth",
        {
            "apply_to": ["a"],
            "method": "time_constant",
            "time_constant": 30,
            "result": "add",
        },
    ),
]


def checked(*steps, slots=("a", "b")):
    """What the compiler says about a chain of steps, valid or not."""
    return validate_pipeline(chained(steps=list(steps), slots=slots))


def issues(result, severity="error"):
    return [
        (item.code, item.parameter_path, item.message)
        for item in result.issues
        if item.severity == severity
    ]


def normalized(step):
    compiled = compile_pipeline(chained(steps=[step]))
    params = next(n.params for n in compiled.definition.nodes if n.id == step[0])
    return params, compiled.fingerprint


def prepared(*steps):
    return PrepareStage(ExecutionPlan(chained_execution(steps=list(steps))))


def local(zone, *moment):
    return datetime(*moment, tzinfo=ZoneInfo(zone)).timestamp()


def calendar(zone, now):
    step = TimeFeatures(TimeParameters(elapsed=False, **CALENDAR, timezone=zone))
    return step.apply({}, Clock(now, None))


def reading(index):
    return {"a": float(index % 7 - 3), "b": 1.0 + (index % 5) / 2}


def moment(index):
    """Observations a few seconds apart, never evenly."""
    return START + 10 * index + (index % 3)


def test_time_features_follow_the_arriving_ones_with_known_ranges():
    result = checked(("clock", "prepare.time", {**CALENDAR, "timezone": "Asia/Tokyo"}))
    assert result.valid and not result.issues
    arriving, added = result.features["clock"][:2], result.features["clock"][2:]
    assert [item.name for item in arriving] == ["a", "b"]
    assert [(item.name, item.minimum, item.maximum) for item in added] == [
        ("dt", POSITIVE, None),
        ("hour", 0.0, 24.0),
        ("weekday", 1.0, 7.0),
        ("hour_sin", -1.0, 1.0),
        ("hour_cos", -1.0, 1.0),
        ("weekday_sin", -1.0, 1.0),
        ("weekday_cos", -1.0, 1.0),
    ]
    # They come from the observation's time, not from a reading.
    for item in added:
        assert item.slots == [] and not item.raw
        assert item.previous is None and item.steps == ["clock"]
    assert tuple(TIME_FEATURES) == TIME_SETTINGS
    # A draft without settings adds what the defaults add.
    assert time_names({}) == ["dt"]
    assert time_names({"elapsed": False, "weekly_cycle": True}) == [
        "weekday_sin",
        "weekday_cos",
    ]


def test_dt_is_above_zero_so_a_rate_per_second_skips_nothing():
    assert POSITIVE > 0 and POSITIVE / 2 == 0
    rate = ("rate", "prepare.formula", {"expression": "a / dt", "name": "rate"})
    result = checked(CLOCK, rate)
    assert result.valid and not result.issues
    # A feature that can be 0 still warns.
    bounded = ("limits", "prepare.range", {"apply_to": ["b"], "low": 0.0, "high": 5})
    risky = ("rate", "prepare.formula", {"expression": "a / b", "name": "rate"})
    assert [code for code, _, _ in issues(checked(bounded, risky), "warning")] == [
        "values"
    ]


@pytest.mark.parametrize(
    "params,slots,expected",
    [
        (
            {},
            ("dt", "b"),
            (
                "scope",
                ["elapsed"],
                "dt already arrives here. Rename that feature before this step.",
            ),
        ),
        (
            {"weekly_cycle": True},
            ("a", "weekday_cos"),
            (
                "scope",
                ["weekly_cycle"],
                "weekday_cos already arrives here. Rename that feature before "
                "this step.",
            ),
        ),
        (
            {"hour": True, "timezone": "Mars/Olympus"},
            ("a", "b"),
            (
                "parameters",
                ["timezone"],
                "Unknown time zone. Write a name such as Europe/Berlin, or UTC.",
            ),
        ),
        (
            {"hour": True, "timezone": "../etc/passwd"},
            ("a", "b"),
            (
                "parameters",
                ["timezone"],
                "Unknown time zone. Write a name such as Europe/Berlin, or UTC.",
            ),
        ),
        (
            {"elapsed": False},
            ("a", "b"),
            ("parameters", [], "Choose at least one time feature."),
        ),
    ],
)
def test_the_compiler_names_what_is_wrong_with_a_time_features_step(
    params, slots, expected
):
    result = checked(("clock", "prepare.time", params), slots=slots)
    assert issues(result) == [expected]


def test_settings_a_step_does_not_read_change_no_fingerprint():
    plain, fingerprint = normalized(CLOCK)
    assert plain == {
        "elapsed": True,
        "hour": False,
        "weekday": False,
        "daily_cycle": False,
        "weekly_cycle": False,
    }
    # Only the hour and the weekday follow a time zone.
    berlin = {"timezone": "Europe/Berlin"}
    assert normalized(("clock", "prepare.time", berlin)) == (plain, fingerprint)
    hourly, _ = normalized(("clock", "prepare.time", {"hour": True, **berlin}))
    assert hourly["timezone"] == "Europe/Berlin"

    # A Smooth from before time constants existed keeps its settings.
    counted, fingerprint = normalized(("calm", "prepare.smooth", {}))
    assert counted == {"method": "exponential", "window_size": 10}
    unread = {"time_constant": 5.0}
    assert normalized(("calm", "prepare.smooth", unread)) == (counted, fingerprint)
    by_time = {"method": "time_constant", "window_size": 99}
    assert normalized(("calm", "prepare.smooth", by_time))[0] == {
        "method": "time_constant",
        "time_constant": 60.0,
    }


def test_a_step_that_adds_dt_is_ready_with_its_second_observation():
    change = ("change", "prepare.change", {"apply_to": ["a"]})
    report = bounded_validation_report(checked(CLOCK, change))
    assert report.ready_after == {"clock": 2, "change": 3}
    assert report.preparation_observations == 2
    without = ("clock", "prepare.time", {"elapsed": False, "hour": True})
    assert bounded_validation_report(checked(without)).ready_after == {"clock": 1}
    assert step_lead("prepare.time", {}) == 1
    assert step_lead("prepare.time", {"elapsed": False, "hour": True}) == 0
    assert step_lead("prepare.smooth", {"method": "time_constant"}) == 0
    assert step_lead("prepare.smooth", {}) == 9
    assert reads_time("prepare.time", {})
    assert reads_time("prepare.smooth", {"method": "time_constant"})
    assert not reads_time("prepare.smooth", {})
    assert not reads_time("prepare.change", {})


def test_dt_is_the_seconds_since_the_previous_observation():
    stage = prepared(CLOCK)
    outputs = [stage.run(ROW, None, START + after) for after in (0, 1, 3.5, 3600)]
    # Nothing comes before the first observation to measure from.
    assert outputs[0] == Withheld("preparing")
    assert [item["clock.dt"] for item in outputs[1:]] == [1.0, 2.5, 3596.5]
    assert outputs[1] == {"clock.a": 3.0, "clock.b": 2.0, "clock.dt": 1.0}
    assert stage.required == 2 and stage.status()["ready"]


def test_the_hour_and_the_weekday_follow_the_clock_of_the_time_zone():
    # India is five and a half hours ahead of UTC.
    assert calendar("Asia/Kolkata", local("UTC", 2026, 1, 1))["hour"] == 5.5
    # Thursday 1 January 2026 in UTC is still Wednesday evening in New York.
    assert calendar("UTC", local("UTC", 2026, 1, 1, 2))["weekday"] == 4.0
    assert calendar("America/New_York", local("UTC", 2026, 1, 1, 2)) == pytest.approx(
        {
            "hour": 21.0,
            "weekday": 3.0,
            "hour_sin": math.sin(2 * math.pi * 21 / 24),
            "hour_cos": math.cos(2 * math.pi * 21 / 24),
            "weekday_sin": math.sin(2 * math.pi * (2 + 21 / 24) / 7),
            "weekday_cos": math.cos(2 * math.pi * (2 + 21 / 24) / 7),
        }
    )
    # Minutes and seconds are a fraction of the hour.
    quarter = calendar("Europe/Berlin", local("Europe/Berlin", 2026, 6, 3, 18, 15, 36))
    assert quarter["hour"] == pytest.approx(18.26)
    # The clock skips an hour when daylight saving time starts.
    before = local("Europe/Berlin", 2026, 3, 29, 1, 59, 59)
    assert calendar("Europe/Berlin", before)["hour"] == pytest.approx(2 - 1 / 3600)
    assert calendar("Europe/Berlin", before + 1)["hour"] == 3.0
    assert calendar("UTC", before + 1)["hour"] == 1.0


def test_cycles_put_the_end_of_a_day_and_a_week_next_to_their_start():
    def point(now, name):
        values = calendar("Europe/Berlin", now)
        return values[f"{name}_sin"], values[f"{name}_cos"]

    # Sunday 8 March 2026, half a minute before Monday.
    sunday = local("Europe/Berlin", 2026, 3, 8, 23, 59, 30)
    late, early = (
        calendar("Europe/Berlin", sunday),
        calendar("Europe/Berlin", sunday + 60),
    )
    assert (late["weekday"], early["weekday"]) == (7.0, 1.0)
    assert late["hour"] - early["hour"] == pytest.approx(24 - 1 / 60)
    for name in ("hour", "weekday"):
        assert math.dist(point(sunday, name), point(sunday + 60, name)) < 0.005
    # Midnight is at the top of the daily circle and noon at the bottom.
    monday = local("Europe/Berlin", 2026, 3, 9)
    assert point(monday, "hour") == pytest.approx((0.0, 1.0))
    assert point(monday + 6 * 3600, "hour") == pytest.approx((1.0, 0.0))
    assert point(monday + 12 * 3600, "hour") == pytest.approx((0.0, -1.0))
    # The week starts on Monday and is half over on Thursday at noon.
    assert point(monday, "weekday") == pytest.approx((0.0, 1.0))
    assert point(monday + 3.5 * 86400, "weekday") == pytest.approx((0.0, -1.0))
    rng = random.Random(7)
    for _ in range(300):
        values = calendar("Europe/Berlin", monday + rng.uniform(0, 400 * 86400))
        assert 0 <= values["hour"] < 24 and values["weekday"] in range(1, 8)
        for name in ("hour", "weekday"):
            sine, cosine = values[f"{name}_sin"], values[f"{name}_cos"]
            assert math.hypot(sine, cosine) == pytest.approx(1.0)


def test_a_time_outside_the_calendar_skips_the_observation():
    stage = prepared(("clock", "prepare.time", {"elapsed": False, "hour": True}))
    with pytest.raises(PrepareRejected, match="outside the calendar") as failure:
        stage.run(ROW, None, 1e18)
    assert (failure.value.node_id, failure.value.reason) == ("clock", "out_of_range")
    assert stage.run(ROW, None, START)["clock.hour"] == 8.0


def test_an_observation_that_is_not_later_than_the_one_before_is_skipped():
    stage = prepared(CLOCK, ("total", "prepare.accumulate", {"apply_to": ["a"]}))
    stage.run(ROW, None, START)
    stage.run(ROW, None, START + 10)
    kept = stage.export_state()
    for late in (START + 10, START + 4, math.nan):
        with pytest.raises(PrepareRejected, match="not later than the one") as failure:
            stage.run(ROW, None, late)
        assert (failure.value.node_id, failure.value.reason) == (
            "clock",
            "out_of_order",
        )
    assert stage.rejected == 3
    # Nothing else changed, so the next observation measures from the last kept.
    assert {**stage.export_state(), "rejected": 0} == kept
    following = stage.run(ROW, None, START + 15)
    assert (following["total.dt"], following["total.a_total"]) == (5.0, 6.0)


def test_dt_after_a_gate_spans_the_observations_the_gate_held_back():
    gate = ("gate", "prepare.gate", {"condition": "a > 0"})
    rows = [(0, 1.0), (10, 1.0), (20, -1.0), (30, -1.0), (40, 1.0)]

    def seconds(stage, name):
        outputs = [stage.run({"a": a, "b": 0.0}, None, START + at) for at, a in rows]
        return [None if isinstance(item, Withheld) else item[name] for item in outputs]

    # Before the Gate every observation counts; after it only those that pass.
    assert seconds(prepared(CLOCK, gate), "gate.dt") == [None, 10.0, None, None, 10.0]
    assert seconds(prepared(gate, CLOCK), "clock.dt") == [None, 10.0, None, None, 30.0]


def test_taking_an_observation_back_restores_when_the_steps_last_ran():
    stage = prepared(*STEPS)
    for index in range(4):
        stage.run(reading(index), None, moment(index))
    before = pickle.dumps(stage.export_state())
    stage.run(reading(4), None, moment(4))
    assert stage.times == {"clock": moment(4), "calm": moment(4)}
    stage.revert()
    assert pickle.dumps(stage.export_state()) == before
    assert stage.times == {"clock": moment(3), "calm": moment(3)}


def test_a_checkpoint_continues_the_time_of_every_step_that_reads_it():
    plan = ExecutionPlan(chained_execution(steps=STEPS))
    stage = PrepareStage(plan)
    # The first observation reaches the clock only: the steps after it wait.
    stage.run(reading(0), None, moment(0))
    assert stage.export_state()["times"] == {"clock": moment(0)}
    for index in range(1, 6):
        stage.run(reading(index), None, moment(index))
    state = pickle.loads(pickle.dumps(stage.export_state()))
    assert state["times"] == {"clock": moment(5), "calm": moment(5)}
    restored = PrepareStage(plan)
    restored.load_state(state)
    following = restored.run(reading(6), None, moment(6))
    assert following == stage.run(reading(6), None, moment(6))
    assert following["calm.dt"] == moment(6) - moment(5)

    def refused(change):
        broken = pickle.loads(pickle.dumps(state))
        change(broken)
        with pytest.raises(ValueError, match="times do not match this design"):
            PrepareStage(plan).load_state(broken)

    refused(lambda item: item.pop("times"))
    refused(lambda item: item["times"].pop("calm"))
    refused(lambda item: item["times"].update(energy=moment(5)))
    refused(lambda item: item["times"].update(calm=math.inf))
    refused(lambda item: item["times"].update(calm=17))

    # A design without such steps keeps loading the checkpoints it wrote before.
    plain = ExecutionPlan(
        chained_execution(steps=[("total", "prepare.accumulate", {})])
    )
    earlier = PrepareStage(plain)
    earlier.run(ROW)
    state = earlier.export_state()
    assert state.pop("times") == {}
    later = PrepareStage(plain)
    later.load_state(state)
    assert later.run(ROW) == earlier.run(ROW)


def test_without_a_time_the_steps_read_the_clock_of_the_machine(monkeypatch):
    ticks = iter([START, START + 2.0])
    monkeypatch.setattr(prepare_module, "time", lambda: next(ticks))
    stage = prepared(CLOCK)
    stage.run(ROW)
    assert stage.run(ROW)["clock.dt"] == 2.0
    # A design that reads no time never asks.
    plain = prepared(("total", "prepare.accumulate", {}))
    assert plain.run(ROW) is not None and plain.times == {}


@pytest.mark.parametrize("time_constant", [0.5, 30.0, 86400.0])
def test_smoothing_by_time_constant_weighs_values_by_their_age(time_constant):
    step = kernel(
        "prepare.smooth", {"method": "time_constant", "time_constant": time_constant}
    )
    assert (step.lead, step.window) == (0, 0)
    rng = random.Random(time_constant)
    state = step.initial()
    values, times = [], []
    now = 0.0
    for index in range(200):
        gap = None if index == 0 else rng.uniform(0.01, 3) * time_constant
        now += gap or 0.0
        values.append(rng.gauss(5, 2))
        times.append(now)
        before = pickle.dumps(state)
        state, actual = step.advance(state, values[-1], gap)
        assert step.accepts(state)
        # The earlier state is left as it was, so a rejection can keep it.
        assert pickle.dumps(pickle.loads(before)) == before
        # Every value weighs exp(-age / time constant), and the first value
        # stands for everything before it.
        ages = [(now - at) / time_constant for at in times]
        weights = [
            math.exp(-age) - (math.exp(-older) if older is not None else 0.0)
            for age, older in zip(ages, [None, *ages], strict=False)
        ]
        expected = math.fsum(w * v for w, v in zip(weights, values, strict=True))
        assert math.fsum(weights) == pytest.approx(1.0)
        assert actual == pytest.approx(expected, rel=1e-9)
        assert min(values) <= actual <= max(values)


def test_smoothing_by_time_constant_does_not_depend_on_how_often_readings_arrive():
    def level(interval, seconds):
        step = kernel("prepare.smooth", {"method": "time_constant"})
        state, actual = step.advance(step.initial(), 0.0)
        for _ in range(round(seconds / interval)):
            state, actual = step.advance(state, 100.0, interval)
        return actual

    # A lasting change shows to 63% after one time constant and to 95% after
    # three, whether readings arrive every second, every ten or once.
    for seconds, share in [(60, 1 - math.exp(-1)), (180, 1 - math.exp(-3))]:
        for interval in (1, 10, seconds):
            assert level(interval, seconds) == pytest.approx(100 * share)
    assert level(1, 60) == pytest.approx(63.2, abs=0.05)
    assert level(1, 180) == pytest.approx(95.0, abs=0.05)
    # Smoothing by a count follows the readings instead.
    by_count = kernel("prepare.smooth", {"window_size": 10})
    slow, fast = by_count.initial(), by_count.initial()
    for _ in range(10):
        slow, once = by_count.advance(slow, 100.0)
    for _ in range(100):
        fast, often = by_count.advance(fast, 100.0)
    assert once == often == 100.0


def test_a_time_constant_names_its_features_and_keeps_their_range():
    def suffix(seconds):
        params = {"method": "time_constant", "time_constant": seconds}
        return default_suffix("prepare.smooth", params)

    assert [suffix(item) for item in (60, 2.5, 0.125, 86400.0)] == [
        "smooth60s",
        "smooth2p5s",
        "smooth0p125s",
        "smooth86400s",
    ]
    assert default_suffix("prepare.smooth", {"window_size": 60}) == "smooth60"
    params = {"method": "time_constant"}
    assert prepared_bounds("prepare.smooth", params, (-1.0, 4.0)) == (-1.0, 4.0)
    step = kernel("prepare.smooth", params)
    assert step.accepts((False, 0.0)) and step.accepts((True, 2.5))
    assert not step.accepts((False, 1.0)) and not step.accepts((True, math.nan))
    assert not step.accepts((3, 2.5)) and not step.accepts((True, 2.5, 0.0))
    # A level that leaves the numbers skips the observation.
    with pytest.raises(ValueError, match="not a finite number") as failure:
        step.advance((True, -1.7e308), 1.7e308, 1e9)
    assert failure.value.reason == "non_finite"
    result = checked(("calm", "prepare.smooth", {**params, "result": "add"}))
    assert result.valid and not result.issues
    assert [item.name for item in result.features["calm"]] == [
        "a",
        "b",
        "a_smooth60s",
        "b_smooth60s",
    ]


def test_steps_that_read_time_keep_no_window():
    def known(steps):
        plan = ExecutionPlan(chained_execution(steps=steps))
        return estimate_resources(plan, 4096).prepare_state_bytes

    by_time = {"apply_to": ["a"], "method": "time_constant"}
    held = {"apply_to": ["a"], "update_when": "a > 0"}
    # A level and whether it was seen, like a held value; alive twice while an
    # observation is staged.
    lane = sys.getsizeof((False, 0.0)) + sys.getsizeof(False) + sys.getsizeof(0.0)
    assert known([("calm", "prepare.smooth", by_time)]) == 2 * lane
    assert known([("calm", "prepare.smooth", by_time)]) == known(
        [("level", "prepare.hold", held)]
    )
    assert known([CLOCK]) == 0


def test_the_stage_computes_rates_energy_and_a_level_from_the_time():
    stage = prepared(*STEPS)
    rows = [(0, 2.0, 1.0), (10, 4.0, 3.0), (15, 8.0, 3.0), (45, 2.0, 0.5)]
    outputs = [stage.run({"a": a, "b": b}, None, START + at) for at, a, b in rows]
    assert outputs[0] == Withheld("preparing")
    assert stage.required == 2 and stage.rejected == 0
    daily = 2 * math.pi * (9 + 10 / 3600) / 24
    assert outputs[1] == pytest.approx(
        {
            "calm.a": 4.0,
            "calm.b": 3.0,
            "calm.dt": 10.0,
            # Eight in the morning in UTC is nine in Berlin, in winter.
            "calm.hour_sin": math.sin(daily),
            "calm.hour_cos": math.cos(daily),
            "calm.rate": 0.4,
            "calm.work": 30.0,
            "calm.work_total": 30.0,
            # The smoothing starts with the first observation it sees.
            "calm.a_smooth30s": 4.0,
        }
    )
    assert [item["calm.work_total"] for item in outputs[1:]] == [30.0, 45.0, 60.0]
    level = 4.0 + (1 - math.exp(-5 / 30)) * (8.0 - 4.0)
    assert outputs[2]["calm.a_smooth30s"] == pytest.approx(level)
    level += (1 - math.exp(-30 / 30)) * (2.0 - level)
    assert outputs[3]["calm.a_smooth30s"] == pytest.approx(level)


@pytest.mark.parametrize("strategy", ["static_baseline", "adaptive_stream"])
def test_time_steps_reach_real_detectors_and_resume_identically(strategy):
    config = AnomalyDetectionConfig(
        pipeline=chained_execution(strategy, STEPS), checkpoint_interval=10000
    )
    constructor = (
        StaticConformalDetectionService
        if strategy == "static_baseline"
        else AdaptiveStreamDetectionService
    )
    service = constructor(config)
    restored = None

    def process(target, index):
        return target.process_data_point(reading(index), timestamp=moment(index))

    try:
        for index in range(28):
            process(service, index)
        if strategy == "static_baseline":
            service._training_future.result(timeout=30)
        result = process(service, 28)
        assert result.should_persist and math.isfinite(result.anomaly_score)
        checkpoint = pickle.loads(pickle.dumps(service.export_checkpoint()))
        restored = constructor.from_checkpoint_data(checkpoint, config)
        for index in range(29, 35):
            actual, expected = process(restored, index), process(service, index)
            assert (
                actual.anomaly_score,
                actual.is_anomaly,
                actual.processed_features,
            ) == (
                expected.anomaly_score,
                expected.is_anomaly,
                expected.processed_features,
            )
        # An observation that arrives a second time is skipped, not scored again.
        with pytest.raises(PrepareRejected, match="not later than the one before"):
            process(restored, 34)
    finally:
        if strategy == "static_baseline":
            service.shutdown()
            if restored is not None:
                restored.shutdown()


def test_a_replay_measures_time_by_when_its_readings_were_measured():
    definition = chained_execution(steps=STEPS).definition
    bound = bind_dataset(
        definition,
        {
            slot.id: BoundSeries(
                id=f"series-{index}", position=index, name=slot.id, unit=None
            )
            for index, slot in enumerate(definition.input_slots)
        },
        run_id="run",
    )
    run = Replay(detection_config(bound, RunAlignment(), 16384))
    # Readings from years ago, the second of each pair a moment after the first.
    start = datetime(2020, 1, 1, tzinfo=UTC).timestamp()
    stage = run.detector.primary_service.prepare
    try:
        for index in range(12):
            at = start + 60 * index
            assert run.step(series_topic(0), at, 1.0 + index) is None
            assert run.step(series_topic(1), at + 0.25, 2.0) is not None
            # An observation is measured when its latest reading is.
            assert stage.times["clock"] == at + 0.25
        assert stage.rejected == 0
        assert stage.states["energy"][0][1] == pytest.approx(11 * 2.0 * 60)
    finally:
        run.close()
