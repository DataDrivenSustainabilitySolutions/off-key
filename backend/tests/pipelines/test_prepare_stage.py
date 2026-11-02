"""The Prepare stage in both RADAR runtimes: warm-up, rejection, restore, fitting."""

import math
import pickle
from itertools import pairwise

import numpy as np
import pytest
from aberrant.compose import INPUT, GraphNode
from off_key_core.models.pipelines import compile_pipeline, execution_fingerprint
from off_key_core.schemas.pipelines import (
    BoundInput,
    PipelineDefinition,
    PipelineExecutionConfig,
    PipelineRuntimeState,
)
from off_key_mqtt_radar.adaptive_detector import (
    AdaptiveStreamDetectionService,
    AdaptiveStreamState,
)
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig
from off_key_mqtt_radar.detector import (
    StaticConformalDetectionService,
    StaticConformalState,
)
from off_key_mqtt_radar.execution_errors import ObservationRejected, StepRejected
from off_key_mqtt_radar.health_monitor import HealthMonitor
from off_key_mqtt_radar.pipelines.adapters import adaptive_graph
from off_key_mqtt_radar.pipelines.batch import BatchFeatureGraph
from off_key_mqtt_radar.pipelines.components import Prepared
from off_key_mqtt_radar.pipelines.plan import ExecutionPlan
from off_key_mqtt_radar.pipelines.prepare import (
    PrepareRejected,
    PrepareStage,
    Withheld,
)
from off_key_mqtt_radar.pipelines.resources import estimate_resources
from off_key_mqtt_radar.preflight import preflight
from sklearn.preprocessing import StandardScaler

from tests.support.adaptive_pipeline import adaptive_pipeline_config

pytestmark = pytest.mark.radar_integration

SLOTS = ("a", "b")
MODELS = {
    "static_baseline": (
        "detector:pyod_iforest",
        {"n_estimators": 10},
        "policy.martingale",
        "static.standard_scaler",
    ),
    "adaptive_stream": (
        "detector:aberrant_moving_mahalanobis_distance",
        {"window_size": 5},
        "policy.quantile",
        "adaptive.standard_scaler",
    ),
}


def execution(
    strategy="adaptive_stream",
    *,
    window=3,
    method="exponential",
    guard=None,
    scale=True,
):
    """Smooth a, add the change of a and b, optionally guard b, then scale."""
    detector, params, policy, scaler = MODELS[strategy]
    smooth = {"apply_to": ["a"], "window_size": window, "method": method}
    steps = [
        ("smooth", "prepare.smooth", smooth),
        ("change", "prepare.change", {}),
    ]
    if guard is not None:
        steps.insert(0, ("guard", "prepare.range", guard))
    if scale:
        steps.append(("scale", scaler, {}))
    ids = ["input", *(identifier for identifier, _, _ in steps)]
    definition = compile_pipeline(
        PipelineDefinition.model_validate(
            {
                "strategy": strategy,
                "input_slots": [{"id": slot, "label": slot.title()} for slot in SLOTS],
                "nodes": [
                    {"id": "input", "kind": "source", "component": "source.aligned"},
                    *(
                        {
                            "id": identifier,
                            "kind": "transform",
                            "component": component,
                            "params": step,
                        }
                        for identifier, component, step in steps
                    ),
                    {
                        "id": "model",
                        "kind": "detector",
                        "component": detector,
                        "params": params,
                    },
                    {"id": "policy", "kind": "policy", "component": policy},
                    {"id": "output", "kind": "output", "component": "output.evidence"},
                ],
                "edges": [
                    *(
                        {"source": source, "target": target}
                        for source, target in pairwise(ids)
                    ),
                    {"source": ids[-1], "target": "model"},
                    {"source": "model", "target": "policy"},
                    {"source": "policy", "target": "output"},
                ],
                "settings": {
                    "training_window_size": 20 if strategy == "static_baseline" else 4,
                    "calibration_window_size": 5
                    if strategy == "static_baseline"
                    else 3,
                },
            }
        )
    ).definition
    bindings = [
        BoundInput(
            slot_id=slot,
            reading_id=f"reading-{slot}",
            entity_id="charger",
            accepted_topic=f"telemetry/charger/{slot}",
            input_key=f"reading_{slot}",
        )
        for slot in SLOTS
    ]
    return PipelineExecutionConfig(
        definition=definition,
        bindings=bindings,
        run_id="run",
        revision_id="revision",
        fingerprint=execution_fingerprint(definition, bindings),
    )


def reading(index):
    return {
        "reading_a": 10.0 + math.sin(index) + (index % 3),
        "reading_b": 50.0 + index % 5,
    }


def bound(plan, index):
    return plan.bind(reading(index))


def outputs(stage, plan, indices):
    return [stage.run(bound(plan, index)) for index in indices]


def test_the_stage_waits_for_its_longest_chain_then_hands_over_its_columns():
    plan = ExecutionPlan(execution(window=3))
    stage = PrepareStage(plan)
    # Smooth outputs from observation 3, Change one observation later.
    assert stage.required == 4
    rows = outputs(stage, plan, range(1, 7))
    assert rows[:3] == [Withheld("preparing")] * 3
    assert all(list(row) == plan.input_columns for row in rows[3:])
    assert plan.input_columns == [
        "change.a",
        "change.b",
        "change.a_diff1",
        "change.b_diff1",
    ]
    # a is smoothed with alpha 0.5 from the first value on; b stays raw.
    level = None
    for index in range(1, 7):
        value = reading(index)["reading_a"]
        level = value if level is None else level + 0.5 * (value - level)
        if index == 5:
            previous = level
    assert rows[-1]["change.a"] == pytest.approx(level)
    assert rows[-1]["change.a_diff1"] == pytest.approx(level - previous)
    assert rows[-1]["change.b"] == reading(6)["reading_b"]
    assert (
        rows[-1]["change.b_diff1"] == reading(6)["reading_b"] - reading(5)["reading_b"]
    )
    assert stage.status() == {
        "ready": True,
        "observed": 4,
        "required": 4,
        "rejected": 0,
        "held_back": 0,
    }


def test_a_rejected_observation_changes_no_state():
    guard = {"apply_to": ["b"], "low": 0.0, "high": 100.0, "action": "skip"}
    plan = ExecutionPlan(execution(guard=guard))
    stage = PrepareStage(plan)
    reference = PrepareStage(plan)
    outputs(stage, plan, range(1, 6))
    outputs(reference, plan, range(1, 6))
    before = pickle.dumps(stage.export_state()["states"])
    with pytest.raises(PrepareRejected) as rejected:
        stage.run(plan.bind({"reading_a": 1.0, "reading_b": 1000.0}))
    assert isinstance(rejected.value, ObservationRejected)
    assert (rejected.value.node_id, rejected.value.reason) == ("guard", "out_of_range")
    assert str(rejected.value) == "b: 1000 is above 100"
    assert pickle.dumps(stage.export_state()["states"]) == before
    assert (stage.accepted, stage.rejected) == (5, 1)
    assert outputs(stage, plan, range(6, 12)) == outputs(reference, plan, range(6, 12))


@pytest.mark.parametrize("cut", range(9))
def test_restoring_at_any_point_continues_the_same_history(cut):
    plan = ExecutionPlan(execution(window=4))
    expected = outputs(PrepareStage(plan), plan, range(1, 10))
    stage = PrepareStage(plan)
    outputs(stage, plan, range(1, cut + 1))
    restored = PrepareStage(plan)
    restored.load_state(pickle.loads(pickle.dumps(stage.export_state())))
    assert outputs(restored, plan, range(cut + 1, 10)) == expected[cut:]


def test_a_prepare_state_of_another_design_is_refused():
    stage = PrepareStage(ExecutionPlan(execution(window=3)))
    other = PrepareStage(ExecutionPlan(execution(window=5)))
    plan = ExecutionPlan(execution(window=5))
    outputs(other, plan, range(1, 8))
    with pytest.raises(ValueError, match="state of smooth is invalid"):
        stage.load_state(other.export_state())
    with pytest.raises(ValueError, match="does not match"):
        stage.load_state({**stage.export_state(), "states": {}})
    with pytest.raises(ValueError, match="unknown format"):
        stage.load_state({"version": 2})


def test_the_learned_graph_picks_the_prepared_columns():
    plan = ExecutionPlan(execution())
    graph, _ = adaptive_graph(plan)
    first = graph.nodes[0]
    assert first.id == "change" and isinstance(first.transformer, Prepared)
    assert [node.id for node in graph.nodes] == ["change", "scale"]
    assert graph.nodes[1].input == "change"
    # A design without Prepare steps keeps its graph, so its checkpoints restore.
    legacy = adaptive_graph(ExecutionPlan(adaptive_pipeline_config().pipeline))[0]
    assert not any(
        isinstance(node, GraphNode) and isinstance(node.transformer, Prepared)
        for node in legacy.nodes
    )
    assert legacy.nodes[0].input == INPUT


def _scores(service, indices):
    return [service.process_data_point(reading(index)) for index in indices]


def test_adaptive_monitoring_prepares_then_warms_up_and_restores_its_history():
    config = AnomalyDetectionConfig(pipeline=execution(window=3))
    service = AdaptiveStreamDetectionService(config)
    results = _scores(service, range(1, 17))
    phases = [result.context["adaptive_stream"]["phase"] for result in results]
    assert phases[:3] == ["preparing"] * 3
    assert phases[3] == "warmup"
    assert phases[-1] == "operational"
    assert service.processed_count == 16
    # Raw readings stay in the evidence; the detector sees prepared, scaled values.
    assert results[-1].raw_data == reading(16)
    assert set(results[-1].processed_features) == {"a", "b", "a_diff1", "b_diff1"}
    checkpoint = pickle.loads(pickle.dumps(service.export_checkpoint()))
    restored = AdaptiveStreamDetectionService.from_checkpoint_data(checkpoint, config)
    later = range(17, 24)
    assert [item.anomaly_score for item in _scores(restored, later)] == [
        item.anomaly_score for item in _scores(service, later)
    ]
    state = PipelineRuntimeState.model_validate(service.get_pipeline_state())
    assert state.preparation is not None and state.preparation.ready
    smooth = state.nodes["smooth"]
    assert (smooth.state, smooth.readiness_observed, smooth.readiness_required) == (
        "ready",
        3,
        3,
    )
    assert state.nodes["change"].learn_count == service.processed_count - 2
    assert state.nodes["scale"].learned_updates == service.processed_count - 3


def test_a_skipped_observation_is_a_coverage_gap_not_a_failure():
    guard = {"apply_to": ["b"], "low": 0.0, "high": 100.0, "action": "skip"}
    config = AnomalyDetectionConfig(pipeline=execution(guard=guard))
    service = AdaptiveStreamDetectionService(config)
    reference = AdaptiveStreamDetectionService(config)
    _scores(service, range(1, 17))
    _scores(reference, range(1, 17))
    assert service.state == AdaptiveStreamState.OPERATIONAL
    with pytest.raises(ObservationRejected):
        service.process_data_point({"reading_a": 1.0, "reading_b": 1000.0})
    assert service.state == AdaptiveStreamState.OPERATIONAL
    assert service.processed_count == reference.processed_count
    assert [item.anomaly_score for item in _scores(service, range(17, 22))] == [
        item.anomaly_score for item in _scores(reference, range(17, 22))
    ]
    state = PipelineRuntimeState.model_validate(service.get_pipeline_state())
    assert state.nodes["guard"].rejections == {"out_of_range": 1}
    assert state.preparation is not None and state.preparation.rejected == 1


def test_a_learned_step_that_skips_an_observation_takes_back_its_preparation(
    monkeypatch,
):
    config = AnomalyDetectionConfig(pipeline=execution(window=3))
    service = AdaptiveStreamDetectionService(config)
    reference = AdaptiveStreamDetectionService(config)
    _scores(service, range(1, 17))
    _scores(reference, range(1, 17))
    scaler = next(
        node.transformer for node in service.pipeline.nodes if node.id == "scale"
    )
    learn = type(scaler).learn_one
    armed = [True]

    def fragile(self, x):
        if armed[0]:
            raise ValueError("scaler broke")
        return learn(self, x)

    monkeypatch.setattr(type(scaler), "learn_one", fragile)
    prepared = pickle.dumps(service.prepare.export_state())
    with pytest.raises(StepRejected, match="scaler broke"):
        service.process_data_point(reading(17))
    # Prepare had committed the observation; skipping it takes that back too.
    assert pickle.dumps(service.prepare.export_state()) == prepared
    armed[0] = False
    assert [item.anomaly_score for item in _scores(service, range(18, 23))] == [
        item.anomaly_score for item in _scores(reference, range(18, 23))
    ]
    state = PipelineRuntimeState.model_validate(service.get_pipeline_state())
    assert state.nodes["scale"].rejections == {"error": 1}
    assert state.preparation is not None and state.preparation.rejected == 0


def test_static_monitoring_prepares_through_fitting_on_one_continuous_history():
    config = AnomalyDetectionConfig(
        pipeline=execution("static_baseline", window=3), checkpoint_interval=10000
    )
    service = StaticConformalDetectionService(config)
    restored = None
    try:
        results = _scores(service, range(1, 29))
        phases = [result.context["static_conformal"]["phase"] for result in results]
        assert phases[:3] == ["preparing"] * 3
        assert phases[3] == "collecting"
        assert phases[-1] == "training_started"
        # Prepared rows are what the baseline buffers.
        assert service.feature_keys == service.plan.input_columns
        discarded = _scores(service, range(29, 32))
        assert all(
            item.context["static_conformal"]["phase"] in {"training_discarded", "ready"}
            for item in discarded
        )
        if service._training_future is not None:
            service._training_future.result(timeout=60)
        reference = PrepareStage(service.plan)
        outputs(reference, service.plan, range(1, 32))
        # Prepare kept running while the baseline fitted in the background.
        assert pickle.dumps(service.prepare.export_state()) == pickle.dumps(
            reference.export_state()
        )
        ready = service.process_data_point(reading(32))
        assert service.state == StaticConformalState.READY
        assert ready.should_persist
        assert set(ready.processed_features) == {"a", "b", "a_diff1", "b_diff1"}
        snapshot = pickle.loads(pickle.dumps(service.export_checkpoint()))
        restored = StaticConformalDetectionService.from_checkpoint_data(
            snapshot, config
        )
        assert (
            restored.process_data_point(reading(33)).anomaly_score
            == service.process_data_point(reading(33)).anomaly_score
        )
    finally:
        service.shutdown()
        if restored is not None:
            restored.shutdown()


def test_the_batch_graph_fits_on_prepared_columns():
    plan = ExecutionPlan(execution("static_baseline"))
    stage = PrepareStage(plan)
    rows = [row for row in outputs(stage, plan, range(1, 30)) if isinstance(row, dict)]
    matrix = np.array([[row[name] for name in plan.input_columns] for row in rows])
    graph = BatchFeatureGraph(plan)
    np.testing.assert_allclose(
        graph.fit_transform(matrix[:20]), StandardScaler().fit_transform(matrix[:20])
    )
    reference = StandardScaler().fit(matrix[:20])
    np.testing.assert_allclose(
        graph.transform(matrix[20:]), reference.transform(matrix[20:])
    )


def test_a_detector_reading_the_prepared_columns_directly():
    plan = ExecutionPlan(execution("static_baseline", scale=False))
    assert plan.learned_nodes == []
    stage = PrepareStage(plan)
    rows = [row for row in outputs(stage, plan, range(1, 12)) if isinstance(row, dict)]
    matrix = np.array([[row[name] for name in plan.input_columns] for row in rows])
    graph = BatchFeatureGraph(plan)
    np.testing.assert_array_equal(graph.fit_transform(matrix), matrix)


def test_admission_counts_prepare_windows_and_prepared_buffers():
    def estimate(window):
        design = execution("static_baseline", window=window, method="rolling")
        return estimate_resources(ExecutionPlan(design), 4096)

    small, large = estimate(3), estimate(3000)
    assert 0 < small.prepare_state_bytes < large.prepare_state_bytes
    # The smoothed feature keeps 3,000 doubles, twice while a pass is staged.
    assert large.prepare_state_bytes > 2 * 3000 * 8
    # The baseline buffers the four prepared columns, not the two readings.
    rows = 20 + 5
    assert small.input_buffer_numeric_bytes == rows * 4 * 8
    report = preflight(execution("adaptive_stream"))
    assert report["ok"] and report["resources"]["prepare_state_bytes"] > 0


def test_health_reports_preparation_as_learning_progress():
    stage = HealthMonitor._preparing_stage(
        {"preparation": {"ready": False, "observed": 7, "required": 11}}
    )
    assert stage == (
        "collecting_training",
        "7/11 observations prepared",
        {"current": 7, "target": 11},
    )
    assert HealthMonitor._preparing_stage({"preparation": {"ready": True}}) is None
    assert HealthMonitor._preparing_stage({}) is None
