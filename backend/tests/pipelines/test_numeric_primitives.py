"""Numeric glue composes with existing windows, learning and checkpoint recovery."""

import math
import pickle
from datetime import UTC, datetime
from itertools import pairwise

import numpy as np
import pytest
from off_key_core.models.dojo_runs import BoundSeries, bind_dataset, series_topic
from off_key_core.models.pipeline_combine import combined_columns, row_step
from off_key_core.models.pipeline_prepare import kernel
from off_key_core.models.pipeline_scope import ScopeError
from off_key_core.models.pipelines import compile_pipeline, execution_fingerprint
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


def execution(strategy="adaptive_stream", steps=STEPS):
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
    definition = compile_pipeline(PipelineDefinition.model_validate(data)).definition
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
    assert not step.accepts((True, math.inf))
    assert not step.accepts((False, 1.0))


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
