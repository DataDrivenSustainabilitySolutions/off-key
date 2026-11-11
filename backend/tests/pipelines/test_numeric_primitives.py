"""Numeric glue composes with existing windows, learning and checkpoint recovery."""

import math
import pickle
import random
import statistics
from datetime import UTC, datetime
from itertools import pairwise

import numpy as np
import pytest
from off_key_core.models.dojo_runs import BoundSeries, bind_dataset, series_topic
from off_key_core.models.pipeline_combine import combined_columns, row_step
from off_key_core.models.pipeline_prepare import (
    PrepareFailure,
    default_suffix,
    kernel,
    prepared_bounds,
)
from off_key_core.models.pipeline_scope import ScopeError
from off_key_core.models.pipelines import (
    compile_pipeline,
    execution_fingerprint,
    validate_pipeline,
)
from off_key_core.schemas.dojo import RunAlignment
from off_key_core.schemas.pipelines import (
    FeatureDescription,
    PipelineDefinition,
    PipelineExecutionConfig,
)
from off_key_mqtt_radar.adaptive_detector import AdaptiveStreamDetectionService
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig
from off_key_mqtt_radar.detector import StaticConformalDetectionService
from off_key_mqtt_radar.dojo.replay import Replay, detection_config
from off_key_mqtt_radar.pipelines.plan import ExecutionPlan
from off_key_mqtt_radar.pipelines.prepare import PrepareRejected, PrepareStage
from off_key_mqtt_radar.pipelines.resources import estimate_resources

from tests.support.pipelines import template

pytestmark = pytest.mark.radar_integration

STEPS = [
    ("limit", "prepare.constant", {"name": "limit", "value": 1}),
    ("flag", "prepare.condition", {"name": "high", "condition": "a > limit"}),
    (
        "hits",
        "prepare.rolling",
        {"apply_to": ["high"], "statistic": "sum", "window_size": 3},
    ),
    ("assign", "prepare.set", {"name": "a", "expression": "if(high == 1, a, b)"}),
    ("total", "prepare.accumulate", {"apply_to": ["high"]}),
]


def design(strategy="adaptive_stream", steps=STEPS):
    data = template(strategy).model_dump(mode="json")
    data["input_slots"] = [{"id": key, "label": key.upper()} for key in ("a", "b")]
    data["settings"].update(training_window_size=20, calibration_window_size=5)
    detector = next(node for node in data["nodes"] if node["kind"] == "detector")
    if strategy == "adaptive_stream":
        detector.update(
            component="detector:aberrant_moving_mahalanobis_distance",
            params={"window_size": 5},
        )
    else:
        detector["params"] = {"n_estimators": 10}
    data["nodes"].extend(
        {"id": key, "kind": "transform", "component": component, "params": params}
        for key, component, params in steps
    )
    data["edges"] = [edge for edge in data["edges"] if edge["source"] != "input"] + [
        {"source": source, "target": target}
        for source, target in pairwise(
            ["input", *(key for key, _, _ in steps), "detector"]
        )
    ]
    return PipelineDefinition.model_validate(data)


def checked(*steps):
    """What the compiler says about a chain of steps, valid or not."""
    return validate_pipeline(design(steps=list(steps)))


def execution(strategy="adaptive_stream", steps=STEPS):
    definition = compile_pipeline(design(strategy, steps)).definition
    bindings = [
        dict(
            slot_id=key,
            reading_id=key,
            entity_id="entity",
            accepted_topic=f"telemetry/entity/{key}",
            input_key=key,
        )
        for key in ("a", "b")
    ]
    return PipelineExecutionConfig(
        definition=definition,
        bindings=bindings,
        revision_id="revision",
        run_id="run",
        fingerprint=execution_fingerprint(definition, bindings),
    )


def reading(index):
    return {"a": float(index % 7 - 3), "b": 1.0 + (index % 5) / 2}


def test_constant_flag_and_assignment_keep_other_features_and_lineage():
    columns = [FeatureDescription(name=key, slots=[key]) for key in ("a", "b")]
    row = {"a": -2.0, "b": 3.0}
    for _, component, params in [*STEPS[:2], STEPS[3]]:
        step = row_step(component, params, list(row))
        row = step.apply(row)
        columns = combined_columns(component, params, columns)
    assert row == {"a": 3.0, "b": 3.0, "limit": 1, "high": 0}
    assert list(row) == [item.name for item in columns] == ["a", "b", "limit", "high"]
    assert columns[0].slots == ["a", "b"] and columns[2].slots == []
    assert (columns[3].minimum, columns[3].maximum) == (0, 1)
    assert (
        row_step(
            "prepare.set", {"name": "new", "expression": "a + b"}, list(row)
        ).apply(row)["new"]
        == 6
    )
    for component, params in [
        ("prepare.constant", {"name": "a"}),
        ("prepare.condition", {"name": "a", "condition": "a > 0"}),
    ]:
        with pytest.raises(ScopeError, match="already exists"):
            combined_columns(component, params, columns)


def test_flags_compose_with_a_window_and_assignment_without_discarding_observations():
    plan = ExecutionPlan(execution())
    stage = PrepareStage(plan)
    outputs = [stage.run({"a": float(a), "b": 10.0}) for a in [2, -1, 3, 0, 4]]
    assert stage.required == 3
    assert stage.held_back == stage.rejected == 0
    assert outputs[2] == {
        "total.a": 3,
        "total.b": 10,
        "total.limit": 1,
        "total.high": 1,
        "total.high_sum3": 2,
        "total.high_total": 1,
    }
    assert outputs[3]["total.a"] == 10
    # The accumulator starts when its upstream window is ready.
    assert outputs[4]["total.high_total"] == 2
    assert stage.updates["flag"] == 5 and stage.updates["total"] == 3


@pytest.mark.parametrize("statistic", ["sum", "quantile", "iqr", "mad", "slope"])
@pytest.mark.parametrize("size", [2, 3, 7])
def test_new_window_statistics_match_independent_references(statistic, size):
    values = [-8.0, -1.0, 3.0, 9.0, 2.0, -4.0, 8.0, 10.0, 11.0]
    step = kernel(
        "prepare.rolling",
        {"statistic": statistic, "window_size": size, "quantile": 0.9},
    )
    state = step.initial()
    for index, value in enumerate(values):
        state, actual = step.advance(state, value)
        assert step.accepts(state)
        if index + 1 < size:
            assert actual is None
            continue
        window = np.array(values[index + 1 - size : index + 1])
        expected = {
            "sum": np.sum(window),
            "quantile": np.quantile(window, 0.9, method="linear"),
            "iqr": np.quantile(window, 0.75) - np.quantile(window, 0.25),
            "mad": np.median(np.abs(window - np.median(window))),
            "slope": np.polyfit(np.arange(size), window, 1)[0],
        }[statistic]
        assert actual == pytest.approx(expected)


def _reference(statistic, window):
    """numpy's value of a statistic that places or describes the latest value."""
    latest, size = window[-1], len(window)
    deviations = window - window.mean()
    second = np.mean(deviations**2)
    match statistic:
        case "zscore":
            return deviations[-1] / window.std(ddof=1)
        case "rank":
            ties = np.sum(window == latest) - 1
            return (np.sum(window < latest) + ties / 2) / (size - 1)
        case "rms":
            return np.sqrt(np.mean(window**2))
        case "skewness":
            return np.mean(deviations**3) / second**1.5
        case "kurtosis":
            return np.mean(deviations**4) / second**2 - 3
    median = np.median(window)
    distances = np.abs(window - median)
    spread = 1.4826 * np.median(distances) or math.sqrt(math.pi / 2) * distances.mean()
    return (latest - median) / spread


SCORES = ["zscore", "robust_zscore", "rank", "rms", "skewness", "kurtosis"]


@pytest.mark.parametrize("statistic", SCORES)
@pytest.mark.parametrize("size", [2, 3, 8, 21])
def test_scores_and_shape_statistics_match_numpy_within_their_limits(statistic, size):
    rng = random.Random(size)
    # Repeated values make ties and windows where more than half are equal.
    values = [
        float(rng.choice([0, 0, 0, rng.randint(-3, 3), rng.gauss(50, 3)]))
        for _ in range(200)
    ]
    params = {"statistic": statistic, "window_size": size}
    step = kernel("prepare.rolling", params)
    low, high = prepared_bounds("prepare.rolling", params, (None, None))
    state = step.initial()
    for index, value in enumerate(values):
        state, actual = step.advance(pickle.loads(pickle.dumps(state)), value)
        assert step.accepts(state)
        if index + 1 < size:
            assert actual is None
            continue
        window = np.array(values[index + 1 - size : index + 1])
        assert (low is None or actual >= low) and (high is None or actual <= high)
        if np.all(window == window[0]) and statistic != "rms":
            # One value says nothing about spread or shape; rank sits in the middle.
            assert actual == (0.5 if statistic == "rank" else 0.0)
        else:
            assert actual == pytest.approx(_reference(statistic, window), abs=1e-9)


def test_scores_stay_finite_where_their_powers_would_not():
    huge = [1e200, -1e200, 3e200, 0.0, 2e200]
    tiny = [1e-200, -1e-200, 3e-200, 0.0, 2e-200]
    for statistic in ("zscore", "robust_zscore", "skewness", "kurtosis"):
        results = []
        for values in (huge, tiny, [1.0, -1.0, 3.0, 0.0, 2.0]):
            step = kernel("prepare.rolling", {"statistic": statistic, "window_size": 5})
            state = step.initial()
            for value in values:
                state, result = step.advance(state, value)
            results.append(result)
        # Scores compare values with each other, so the scale drops out.
        assert results[0] == pytest.approx(results[2])
        assert results[1] == pytest.approx(results[2])
    step = kernel("prepare.rolling", {"statistic": "rms", "window_size": 2})
    state, _ = step.advance(step.initial(), 1e200)
    with pytest.raises(PrepareFailure, match="finite"):
        step.advance(state, 1e200)


def test_a_robust_score_survives_a_window_that_is_mostly_one_value():
    step = kernel("prepare.rolling", {"statistic": "robust_zscore", "window_size": 5})
    state = step.initial()
    for value in [0.0, 0.0, 0.0, 0.0, 5.0]:
        state, score = step.advance(state, value)
    # The MAD is 0, so the mean absolute deviation, 1, stands in for it.
    assert score == pytest.approx(5 / math.sqrt(math.pi / 2))


def test_scores_have_ranges_a_unit_interval_detector_can_rely_on():
    def bounds(statistic, size=60, incoming=(None, None)):
        params = {"statistic": statistic, "window_size": size}
        return prepared_bounds("prepare.rolling", params, incoming)

    assert bounds("rank") == (0.0, 1.0)
    assert bounds("zscore", 4) == (-1.5, 1.5)
    assert bounds("skewness", 5) == (-1.5, 1.5)
    assert bounds("kurtosis", 5) == (-2.0, 0.25)
    assert bounds("kurtosis", 2) == (-2.0, 0.0)
    assert bounds("robust_zscore") == (None, None)
    assert bounds("rms") == (0.0, None)
    assert bounds("rms", incoming=(-3.0, 2.0)) == (0.0, 3.0)
    assert bounds("rms", incoming=(1.0, 2.0)) == (1.0, 2.0)
    assert default_suffix("prepare.rolling", {"statistic": "robust_zscore"}) == (
        "robust_zscore60"
    )


@pytest.mark.parametrize(
    "function,expected",
    [
        ("sum", [-2.0, 3.0, 2.0]),
        ("min", [-2.0, -2.0, -2.0]),
        ("max", [-2.0, 5.0, 5.0]),
    ],
)
def test_accumulation_starts_with_the_first_value_and_restores(function, expected):
    step = kernel("prepare.accumulate", {"function": function})
    state = step.initial()
    for value, result in zip([-2.0, 5.0, -1.0], expected, strict=True):
        state, actual = step.advance(pickle.loads(pickle.dumps(state)), value)
        assert actual == result and step.accepts(state)
    assert not step.accepts((True, math.inf, 0.0))
    assert not step.accepts((False, 1.0, 0.0))
    assert not step.accepts((True,))
    # Only a total carries what addition dropped.
    assert step.accepts((True, 1.0, 0.5)) is (function == "sum")


@pytest.mark.parametrize(
    "function,expected", [("sum", 4.5), ("min", 1.5), ("max", 3.0)]
)
def test_accumulation_continues_a_checkpoint_from_before_the_carry(function, expected):
    step = kernel("prepare.accumulate", {"function": function})
    assert step.accepts((True, 1.5)) and step.accepts((False, 0.0))
    assert not step.accepts((True, math.nan)) and not step.accepts((False, 1.0))
    state, actual = step.advance((True, 1.5), 3.0)
    assert actual == expected and len(state) == 3 and step.accepts(state)
    assert step.advance((False, 0.0), 3.0) == ((True, 3.0, 0.0), 3.0)


def test_a_long_total_keeps_what_plain_addition_drops():
    step = kernel("prepare.accumulate", {"function": "sum"})
    state = step.initial()
    values = [1e16, 1.0, 1.0, -1e16, 0.5, 0.5]
    for value in values:
        state, total = step.advance(state, value)
    assert total == math.fsum(values) == 3.0
    plain = 0.0
    for value in values:
        plain += value
    assert plain == 1.0
    state, _ = step.advance(step.initial(), 1e308)
    with pytest.raises(PrepareFailure, match="finite"):
        step.advance(state, 1e308)


@pytest.mark.parametrize("size", [2, 3, 50, 51])
def test_the_median_deviation_is_found_in_the_sorted_window_exactly(size):
    rng = random.Random(size)
    values = [
        float(rng.choice([rng.randint(-3, 3), rng.gauss(0, 5)])) for _ in range(300)
    ]
    step = kernel("prepare.rolling", {"statistic": "mad", "window_size": size})
    state = step.initial()
    for index, value in enumerate(values):
        state, actual = step.advance(state, value)
        if index + 1 < size:
            continue
        window = values[index + 1 - size : index + 1]
        median = statistics.median(window)
        assert actual == statistics.median(abs(item - median) for item in window)


@pytest.mark.parametrize(
    ("quantile", "suffix"),
    [
        (0.9, "q90_60"),
        (0.1, "q10_60"),
        (0.999, "q99p9_60"),
        (0.125, "q12p5_60"),
        (0.3, "q30_60"),
        (0.0, "q0_60"),
        (1.0, "q100_60"),
    ],
)
def test_a_rolling_quantile_is_named_after_its_quantile(quantile, suffix):
    params = {"statistic": "quantile", "quantile": quantile, "window_size": 60}
    assert default_suffix("prepare.rolling", params) == suffix
    assert default_suffix("prepare.rolling", {"statistic": "iqr"}) == "iqr60"


def test_two_quantiles_of_one_window_sit_side_by_side():
    band = [
        (
            f"q{percent}",
            "prepare.rolling",
            {
                "apply_to": ["a"],
                "statistic": "quantile",
                "quantile": percent / 100,
                "window_size": 6,
            },
        )
        for percent in (10, 90)
    ]
    result = checked(*band)
    assert result.valid
    assert [item.name for item in result.features["q90"]] == [
        "a",
        "b",
        "a_q10_6",
        "a_q90_6",
    ]


def test_set_continues_the_feature_it_reads_and_starts_one_it_does_not():
    smooth = ("smooth", "prepare.smooth", {"apply_to": ["a"], "window_size": 5})
    guarded = checked(
        smooth,
        ("assign", "prepare.set", {"name": "a", "expression": "if(a > 0, a, b)"}),
    ).features["assign"][0]
    assert (guarded.name, guarded.steps) == ("a", ["smooth", "assign"])
    assert guarded.previous == "smooth.a" and guarded.slots == ["a", "b"]
    assert not guarded.raw
    fresh = checked(
        smooth, ("assign", "prepare.set", {"name": "a", "expression": "b * 2"})
    ).features["assign"][0]
    assert (fresh.name, fresh.steps, fresh.previous) == ("a", ["assign"], None)
    assert fresh.slots == ["b"]


@pytest.mark.parametrize("name", ["a", "ratio", "_x1"])
def test_set_replaces_any_feature_and_adds_names_a_formula_can_read(name):
    result = checked(("assign", "prepare.set", {"name": name, "expression": "a + b"}))
    assert result.valid


@pytest.mark.parametrize("name", ["my feature", "tick`", "1st", "a-b"])
def test_set_refuses_a_new_name_no_formula_could_read(name):
    result = checked(("assign", "prepare.set", {"name": name, "expression": "a + b"}))
    assert [(issue.code, issue.parameter_path) for issue in result.issues] == [
        ("scope", ["name"])
    ]
    assert "letters, digits and underscores" in result.issues[0].message


def warnings(result):
    return [
        (issue.code, issue.node_id, issue.message)
        for issue in result.issues
        if issue.severity == "warning"
    ]


@pytest.mark.parametrize(
    ("condition", "message"),
    [
        ("a > 20", "The condition is never true, so the flag is always 0."),
        ("a >= 0", "The condition is always true, so the flag is always 1."),
    ],
)
def test_a_flag_that_never_changes_is_pointed_out(condition, message):
    result = checked(
        ("range", "prepare.range", {"low": 0, "high": 10}),
        ("flag", "prepare.condition", {"name": "flag", "condition": condition}),
        ("keep", "features.select", {"features": ["a", "b"]}),
    )
    assert result.valid
    assert warnings(result) == [("values", "flag", message)]


def test_a_set_feature_that_reads_nothing_is_pointed_out():
    result = checked(
        ("assign", "prepare.set", {"name": "a", "expression": "1 + 2"}),
        ("keep", "features.select", {"features": ["b"]}),
    )
    assert warnings(result) == [
        (
            "values",
            "assign",
            "The formula reads no feature, so its value never changes.",
        )
    ]


def test_a_feature_that_never_changes_is_pointed_out_where_something_learns():
    limit = ("limit", "prepare.constant", {"name": "limit", "value": 80})
    message = (
        "limit is always 80, so {} learns nothing from it. Use it in a formula "
        "or condition, then leave it out with Select features."
    )
    assert warnings(checked(limit)) == [
        (
            "constant_feature",
            "detector",
            message.format("Aberrant MovingMahalanobisDistance"),
        )
    ]
    used = ("over", "prepare.condition", {"name": "over", "condition": "a > limit"})
    keep = ("keep", "features.select", {"features": ["a", "b", "over"]})
    assert warnings(checked(limit, used, keep)) == []
    # A scaler that is not given the constant has nothing to say about it; the
    # scaler that is given it reports it, and after scaling it has no range.
    scoped = ("scale", "adaptive.standard_scaler", {"apply_to": ["a", "b"]})
    assert [node for _, node, _ in warnings(checked(limit, scoped))] == ["detector"]
    scaled = ("scale", "adaptive.standard_scaler", {})
    assert [node for _, node, _ in warnings(checked(limit, scaled))] == ["scale"]


def test_rejection_rolls_back_accumulation_and_window_state():
    steps = [*STEPS, ("guard", "prepare.formula", {"expression": "1 / b"})]
    plan = ExecutionPlan(execution(steps=steps))
    stage = PrepareStage(plan)
    for index in range(5):
        stage.run(reading(index))
    before = pickle.dumps(stage.export_state()["states"])
    with pytest.raises(PrepareRejected, match="Division by 0"):
        stage.run({"a": 3.0, "b": 0.0})
    assert pickle.dumps(stage.export_state()["states"]) == before
    restored = PrepareStage(plan)
    restored.load_state(pickle.loads(pickle.dumps(stage.export_state())))
    assert restored.run(reading(7)) == stage.run(reading(7))


@pytest.mark.parametrize("strategy", ["static_baseline", "adaptive_stream"])
def test_primitives_reach_real_detectors_and_resume_identically(strategy):
    config = AnomalyDetectionConfig(
        pipeline=execution(strategy), checkpoint_interval=10000
    )
    constructor = (
        StaticConformalDetectionService
        if strategy == "static_baseline"
        else AdaptiveStreamDetectionService
    )
    service = constructor(config)
    restored = None
    try:
        for index in range(27):
            service.process_data_point(reading(index))
        if strategy == "static_baseline":
            service._training_future.result(timeout=30)
        result = service.process_data_point(reading(27))
        assert result.should_persist and math.isfinite(result.anomaly_score)
        checkpoint = pickle.loads(pickle.dumps(service.export_checkpoint()))
        restored = constructor.from_checkpoint_data(checkpoint, config)
        for index in range(28, 34):
            actual = restored.process_data_point(reading(index))
            expected = service.process_data_point(reading(index))
            assert (
                actual.anomaly_score,
                actual.is_anomaly,
                actual.processed_features,
            ) == (
                expected.anomaly_score,
                expected.is_anomaly,
                expected.processed_features,
            )
    finally:
        if strategy == "static_baseline":
            service.shutdown()
            if restored is not None:
                restored.shutdown()


@pytest.mark.parametrize("strategy", ["static_baseline", "adaptive_stream"])
def test_primitives_replay_historical_data_without_filtering_observations(strategy):
    definition = execution(strategy).definition
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
    run = Replay(detection_config(bound, RunAlignment(), 512))
    start = datetime(2020, 1, 1, tzinfo=UTC).timestamp()
    rows = []
    try:
        for index in range(40):
            for position, value in enumerate(reading(index).values()):
                row = run.step(series_topic(position), start + index, value)
                if row is not None:
                    rows.append(row)
        assert len(rows) == 40
        assert rows[-1].phase == (
            "ready" if strategy == "static_baseline" else "operational"
        )
        assert rows[-1].score is not None and math.isfinite(rows[-1].score)
        assert set(run.stats()) <= {
            "stale_sensor_block",
            "waiting_for_all",
            "waiting_for_barrier",
        }
    finally:
        run.close()


def test_new_statistics_have_safe_bounds_and_ignore_unused_quantile_parameters():
    for statistic in ["sum", "quantile", "iqr", "mad", "slope"]:
        plan = ExecutionPlan(
            execution(
                steps=[
                    ("range", "prepare.range", {"low": -2.0, "high": 3.0}),
                    (
                        "rolling",
                        "prepare.rolling",
                        {"statistic": statistic, "window_size": 3},
                    ),
                ]
            )
        )
        column = plan.compiled.features["rolling"][-1]
        if statistic == "slope":
            assert column.minimum < 0 < column.maximum
        assert estimate_resources(plan, 4096).prepare_state_bytes > 0
    original = execution(steps=[("rolling", "prepare.rolling", {"statistic": "mean"})])
    explicit = execution(
        steps=[("rolling", "prepare.rolling", {"statistic": "mean", "quantile": 0.9})]
    )
    assert original.fingerprint == explicit.fingerprint
