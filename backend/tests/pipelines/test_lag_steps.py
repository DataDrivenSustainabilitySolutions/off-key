"""Lags: one step that adds a feature's values from several observations back."""

import math
import pickle
import random
from array import array
from bisect import bisect_right
from itertools import pairwise

import pytest
from off_key_core.models.pipeline_prepare import (
    default_suffix,
    kernel,
    output_suffixes,
    prepared_bounds,
)
from off_key_core.models.pipelines import (
    compile_pipeline,
    execution_fingerprint,
    validate_pipeline,
)
from off_key_core.schemas.pipelines import (
    LagsParameters,
    PipelineDefinition,
    PipelineExecutionConfig,
)
from off_key_mqtt_radar.adaptive_detector import AdaptiveStreamDetectionService
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig
from off_key_mqtt_radar.detector import StaticConformalDetectionService
from off_key_mqtt_radar.pipelines.plan import ExecutionPlan
from off_key_mqtt_radar.pipelines.prepare import PrepareStage
from pydantic import ValidationError

from tests.support.pipelines import template

pytestmark = pytest.mark.radar_integration


def design(strategy="adaptive_stream", steps=(), slots=("a", "b")):
    """A design that runs steps in a chain between the input and the detector."""
    data = template(strategy).model_dump(mode="json")
    data["input_slots"] = [{"id": key, "label": key.upper()} for key in slots]
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


def checked(*steps, slots=("a", "b")):
    return validate_pipeline(design(steps=list(steps), slots=slots))


def issues(result):
    return [
        (item.code, item.parameter_path, item.message)
        for item in result.issues
        if item.severity == "error"
    ]


def features(result, node):
    return {item.name: item for item in result.features[node]}


def execution(strategy="adaptive_stream", steps=()):
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


COUNTED = {"unit": "observations"}
LAGS = [("lags", "prepare.lags", {"apply_to": ["a"], "lags": [3, 1, 2], **COUNTED})]


def test_lags_give_the_values_several_observations_back():
    step = kernel("prepare.lags", {"lags": [24, 1, 3], **COUNTED})
    assert (step.width, step.lead, step.window) == (3, 24, 24)
    state = step.initial()
    for index in range(30):
        before = pickle.dumps(state)
        state, actual = step.advance(state, float(index))
        assert step.accepts(state)
        # The earlier state is left as it was, so a rejection can keep it.
        assert pickle.dumps(pickle.loads(before)) == before
        if index < 24:
            assert actual is None
        else:
            # Ascending lags: 1, 3 and 24 observations back.
            assert actual == (index - 1.0, index - 3.0, index - 24.0)
    assert not step.accepts((pickle.loads(pickle.dumps(state))[0][:0] * 0,) * 2)
    assert default_suffix("prepare.lags", {}) == "lag"
    assert output_suffixes("prepare.lags", {"lags": [24, 1], **COUNTED}, "lag") == (
        "lag1",
        "lag24",
    )
    assert output_suffixes("prepare.lags", {"lags": [24], "unit": "hours"}, "lag") == (
        "lag24h",
    )
    assert prepared_bounds("prepare.lags", {}, (-1.0, 4.0)) == (-1.0, 4.0)


def test_lag_settings_are_sorted_distinct_and_bounded():
    assert LagsParameters(lags=[24, 1, 2]).lags == [1, 2, 24]
    assert (LagsParameters().lags, LagsParameters().unit) == ([1, 5, 15], "minutes")
    with pytest.raises(ValidationError, match="30 days"):
        LagsParameters(lags=[31], unit="days")
    with pytest.raises(ValidationError, match="add their lags"):
        LagsParameters(result="replace")
    for lags in ([], [1, 1], [0], [3601], list(range(1, 26))):
        with pytest.raises(ValidationError):
            LagsParameters(lags=lags)


def test_a_lags_step_adds_one_feature_per_lag_and_feature():
    result = checked(("lags", "prepare.lags", {"lags": [1, 24], **COUNTED}))
    assert result.valid, issues(result)
    named = features(result, "lags")
    assert list(named) == ["a", "b", "a_lag1", "a_lag24", "b_lag1", "b_lag24"]
    assert named["b_lag24"].slots == ["b"] and not named["b_lag24"].raw
    assert named["a_lag1"].steps == ["lags"]
    custom = checked(("lags", "prepare.lags", {"lags": [2], "suffix": "back"}))
    assert list(features(custom, "lags")) == ["a", "b", "a_back2min", "b_back2min"]
    # A name that is taken is refused, like any other added feature.
    taken = checked(
        ("change", "prepare.change", {"mode": "lag", "lag": 1}),
        ("lags", "prepare.lags", {"lags": [1], **COUNTED}),
    )
    assert issues(taken)[0][2] == "a_lag1 already exists. Choose another suffix."


def test_lag_windows_count_toward_the_prepare_budget():
    over = checked(
        ("lags", "prepare.lags", {"lags": [1, 3600], **COUNTED}),
        slots=tuple("abcdefghijklmn"),
    )
    assert issues(over) == [
        ("prepare_budget", None, "Windows hold 50,400 values; the limit is 50,000.")
    ]


def test_the_stage_adds_lags_beside_the_features_once_the_largest_has_arrived():
    stage = PrepareStage(ExecutionPlan(execution(steps=LAGS)))
    outputs = [stage.run({"a": float(index), "b": 0.5}) for index in range(5)]
    assert stage.required == 4
    assert outputs[3] == {
        "lags.a": 3.0,
        "lags.b": 0.5,
        "lags.a_lag1": 2.0,
        "lags.a_lag2": 1.0,
        "lags.a_lag3": 0.0,
    }
    assert outputs[4]["lags.a_lag3"] == 1.0
    assert all(not isinstance(item, dict) for item in outputs[:3])


def test_a_saved_lags_step_keeps_its_lags_sorted():
    definition = compile_pipeline(design(steps=LAGS)).definition
    node = next(item for item in definition.nodes if item.id == "lags")
    assert node.params["lags"] == [1, 2, 3]
    assert "result" not in node.params


@pytest.mark.parametrize("strategy", ["static_baseline", "adaptive_stream"])
def test_lags_reach_real_detectors_and_resume_identically(strategy):
    config = AnomalyDetectionConfig(
        pipeline=execution(strategy, steps=LAGS), checkpoint_interval=10000
    )
    constructor = (
        StaticConformalDetectionService
        if strategy == "static_baseline"
        else AdaptiveStreamDetectionService
    )
    service = constructor(config)
    restored = None
    try:
        for index in range(30):
            service.process_data_point(reading(index))
        if strategy == "static_baseline":
            service._training_future.result(timeout=30)
        result = service.process_data_point(reading(30))
        assert result.should_persist and math.isfinite(result.anomaly_score)
        checkpoint = pickle.loads(pickle.dumps(service.export_checkpoint()))
        restored = constructor.from_checkpoint_data(checkpoint, config)
        for index in range(31, 36):
            actual = restored.process_data_point(reading(index))
            expected = service.process_data_point(reading(index))
            assert (actual.anomaly_score, actual.processed_features) == (
                expected.anomaly_score,
                expected.processed_features,
            )
    finally:
        if strategy == "static_baseline":
            service.shutdown()
            if restored is not None:
                restored.shutdown()


def _warnings(result):
    return {item.code: item for item in result.issues if item.severity == "warning"}


def test_lags_after_a_gate_or_of_a_held_input_are_no_fixed_time_back():
    gated = checked(
        ("gate", "prepare.gate", {"condition": "b > 1"}),
        ("lags", "prepare.lags", {"lags": [1], **COUNTED}),
    )
    assert gated.valid
    found = _warnings(gated)["lags_after_gate"]
    assert found.node_id == "lags" and "before the Gate" in found.message
    data = design(steps=LAGS).model_dump(mode="json")
    source = next(node for node in data["nodes"] if node["kind"] == "source")
    source["params"] = {"hold": [{"input": "a", "seconds": 600}]}
    held = validate_pipeline(PipelineDefinition.model_validate(data))
    assert held.valid
    assert _warnings(held)["lags_of_held_input"].message.startswith("a is held")
    assert not _warnings(checked(*LAGS))
    # Lags in time look back in time, whatever passes the Gate.
    timed = checked(
        ("gate", "prepare.gate", {"condition": "b > 1"}),
        ("lags", "prepare.lags", {"lags": [1]}),
    )
    assert "lags_after_gate" not in _warnings(timed)


def test_many_lags_are_worth_a_word():
    wide = checked(("lags", "prepare.lags", {"lags": list(range(1, 14))}))
    assert wide.valid
    assert "adds 26 features" in _warnings(wide)["wide_lags"].message
    assert "wide_lags" not in _warnings(
        checked(("lags", "prepare.lags", {"lags": list(range(1, 13))}))
    )


def test_lags_in_time_find_their_value_within_one_percent_of_the_lag():
    rng = random.Random(7)
    step = kernel("prepare.lags", {"lags": [1, 15, 60], "unit": "minutes"})
    assert (step.width, step.lead) == (3, 0)
    state = step.initial()
    history = []
    times = []
    now = 1_700_000_000.0
    for index in range(6000):
        # Irregular readings, about every 2 s, with an outage of ten minutes.
        now += 600.0 if index == 3000 else rng.uniform(0.5, 3.5)
        value = float(index)
        state, actual = step.advance(state, value, now)
        history.append((now, value))
        times.append(now)
        assert step.accepts(state) and len(state[0]) <= step.window
        if now - history[0][0] < 3600:
            assert actual is None and step.waiting(state)
            continue
        assert not step.waiting(state)
        for lag, found in zip((60, 900, 3600), actual, strict=True):
            # Values count the observations, so each names its time.
            found_at = history[int(found)][0]
            exact_at = history[bisect_right(times, now - lag) - 1][0]
            # Never later than asked for, and at most 1% of the lag earlier.
            assert found_at <= now - lag
            assert exact_at - found_at <= 0.01 * lag + 1e-9
    assert step.held == 2 * step.window and step.window < 700
    assert not step.accepts((array("d", [2.0, 1.0]), array("d", [0.0, 0.0])))


def test_the_stage_waits_for_the_longest_lag_in_time():
    lags = [
        ("lags", "prepare.lags", {"apply_to": ["a"], "lags": [10], "unit": "seconds"})
    ]
    stage = PrepareStage(ExecutionPlan(execution(steps=lags)))
    outputs = []
    for second in range(0, 16, 3):
        outputs.append(
            stage.run({"a": float(second), "b": 0.5}, timestamp=1e9 + second)
        )
        assert stage.ready == isinstance(outputs[-1], dict)
    # At 12 s, 10 s back is 2 s: the reading at 0 s is the last before it.
    assert outputs[4]["lags.a_lag10s"] == 0.0
    assert outputs[5]["lags.a_lag10s"] == 3.0
    restored = PrepareStage(ExecutionPlan(execution(steps=lags)))
    restored.load_state(pickle.loads(pickle.dumps(stage.export_state())))
    assert restored.run({"a": 1.0, "b": 0.5}, timestamp=1e9 + 20) == stage.run(
        {"a": 1.0, "b": 0.5}, timestamp=1e9 + 20
    )
