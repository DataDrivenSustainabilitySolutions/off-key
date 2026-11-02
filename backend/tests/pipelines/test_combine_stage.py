"""Gates, Formulas and Aggregates in both RADAR runtimes."""

import math
import pickle
from itertools import pairwise

import pytest
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
from off_key_mqtt_radar.detector import StaticConformalDetectionService
from off_key_mqtt_radar.models import is_held_back
from off_key_mqtt_radar.pipelines.diagnostics import (
    DiagnosticLimits,
    PipelineDiagnostics,
)
from off_key_mqtt_radar.pipelines.plan import ExecutionPlan
from off_key_mqtt_radar.pipelines.prepare import (
    PrepareRejected,
    PrepareStage,
    Withheld,
)
from off_key_mqtt_radar.pipelines.resources import estimate_resources

pytestmark = pytest.mark.radar_integration

SLOTS = ("a", "b")
MODELS = {
    "static_baseline": (
        "detector:pyod_iforest",
        {"n_estimators": 10},
        "policy.martingale",
        {"training_window_size": 20, "calibration_window_size": 5},
    ),
    "adaptive_stream": (
        "detector:aberrant_moving_mahalanobis_distance",
        {"window_size": 5},
        "policy.quantile",
        {"training_window_size": 4, "calibration_window_size": 3},
    ),
}
GATE = ("gate", "prepare.gate", {"condition": "b > 51"})


def execution(*steps, strategy="adaptive_stream"):
    """input, then each (id, component, params) step in order, then the detector."""
    detector, params, policy, settings = MODELS[strategy]
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
                    *({"source": s, "target": t} for s, t in pairwise(ids)),
                    {"source": ids[-1], "target": "model"},
                    {"source": "model", "target": "policy"},
                    {"source": "policy", "target": "output"},
                ],
                "settings": settings,
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


def reading(index, b=None):
    """b cycles through 50 to 54, so b > 51 holds for three of every five."""
    return {
        "reading_a": 10.0 + math.sin(index) + index % 3,
        "reading_b": 50.0 + index % 5 if b is None else b,
    }


def passes(index):
    return reading(index)["reading_b"] > 51


def run(stage, plan, indices, *, closed=()):
    return [
        stage.run(plan.bind(reading(index, b=-1.0 if index in closed else None)))
        for index in indices
    ]


def test_steps_before_a_closed_gate_see_the_observation_and_steps_after_it_do_not():
    plan = ExecutionPlan(
        execution(
            ("smooth", "prepare.smooth", {"apply_to": ["a"], "window_size": 2}),
            ("gate", "prepare.gate", {"condition": "b > 0"}),
            ("change", "prepare.change", {"apply_to": ["a"]}),
        )
    )
    stage = PrepareStage(plan)
    assert stage.required == 3
    rows = run(stage, plan, range(1, 8), closed={3, 4})
    assert rows[:2] == [Withheld("preparing")] * 2
    assert rows[2:4] == [Withheld("held_back", "gate")] * 2
    assert all(isinstance(row, dict) for row in rows[4:])
    assert stage.updates == {"smooth": 7, "gate": 6, "change": 4}
    assert (stage.accepted, stage.rejected, stage.held_back) == (7, 0, 2)
    # Smoothing went on through 3 and 4; Change compares 5 with 2, the last
    # observation that reached it.
    level, levels = None, {}
    for index in range(1, 6):
        value = reading(index)["reading_a"]
        level = value if level is None else level + 2 / 3 * (value - level)
        levels[index] = level
    assert rows[4]["change.a"] == pytest.approx(levels[5])
    assert rows[4]["change.a_diff1"] == pytest.approx(levels[5] - levels[2])


def test_observations_held_back_before_a_window_do_not_fill_it():
    plan = ExecutionPlan(
        execution(
            ("gate", "prepare.gate", {"condition": "b > 0"}),
            ("smooth", "prepare.smooth", {"window_size": 3}),
        )
    )
    stage = PrepareStage(plan)
    status = {"ready": False, "observed": 0, "required": 3, "rejected": 0}
    assert stage.status() == {**status, "held_back": 0}
    assert (
        run(stage, plan, range(1, 6), closed=range(1, 6))
        == [Withheld("held_back", "gate")] * 5
    )
    assert stage.status() == {**status, "held_back": 5}
    assert run(stage, plan, range(6, 8)) == [Withheld("preparing")] * 2
    assert stage.status() == {**status, "observed": 2, "held_back": 5}
    assert isinstance(run(stage, plan, [8])[0], dict)
    assert stage.status() == {**status, "ready": True, "observed": 3, "held_back": 5}


def test_a_formula_without_a_finite_value_skips_the_observation():
    plan = ExecutionPlan(
        execution(
            (
                "ratio",
                "prepare.formula",
                {"expression": "a / (b - 50)", "name": "ratio"},
            ),
            ("mean", "prepare.aggregate", {"function": "mean", "result": "replace"}),
        )
    )
    stage = PrepareStage(plan)
    with pytest.raises(PrepareRejected) as rejected:
        run(stage, plan, [5])
    assert (rejected.value.node_id, rejected.value.reason) == ("ratio", "out_of_domain")
    assert str(rejected.value) == "Division by 0"
    assert (stage.accepted, stage.rejected) == (0, 1)
    (row,) = run(stage, plan, [1])
    values = reading(1)
    ratio = values["reading_a"] / (values["reading_b"] - 50)
    expected = (values["reading_a"] + values["reading_b"] + ratio) / 3
    assert row == {"mean.mean": pytest.approx(expected)}
    assert plan.input_columns == ["mean.mean"]


def test_held_back_counts_survive_a_checkpoint_and_older_checkpoints_load():
    plan = ExecutionPlan(
        execution(GATE, ("smooth", "prepare.smooth", {"window_size": 2}))
    )
    stage = PrepareStage(plan)
    run(stage, plan, range(1, 12))
    state = pickle.loads(pickle.dumps(stage.export_state()))
    assert state["held_back"] == sum(not passes(index) for index in range(1, 12))
    restored = PrepareStage(plan)
    restored.load_state(state)
    assert restored.status() == stage.status()
    assert run(restored, plan, range(12, 18)) == run(stage, plan, range(12, 18))
    # Checkpoints from before Gates existed carry no held-back count.
    older = PrepareStage(plan)
    older.load_state({key: value for key, value in state.items() if key != "held_back"})
    assert (older.held_back, older.accepted) == (0, state["accepted"])
    with pytest.raises(ValueError, match="counts are invalid"):
        PrepareStage(plan).load_state({**state, "held_back": -1})


def test_diagnostics_show_where_an_observation_was_held_back():
    config = execution(
        ("smooth", "prepare.smooth", {"apply_to": ["a"], "window_size": 2}),
        ("gate", "prepare.gate", {"condition": "b > 0"}),
        ("change", "prepare.change", {"apply_to": ["a"]}),
    )
    plan = ExecutionPlan(config)
    stage = PrepareStage(plan)
    diagnostics = PipelineDiagnostics(
        config, DiagnosticLimits(sample_interval_seconds=1e-9)
    )
    diagnostics.external = frozenset(stage.frontier)
    for index in range(1, 6):
        diagnostics.begin(index, "operational")
        stage.run(
            plan.bind(reading(index, b=-1.0 if index == 5 else None)), diagnostics
        )
        diagnostics.finish()
    snapshot = diagnostics.snapshot()
    nodes = snapshot["nodes"]
    assert (nodes["smooth"]["state"], nodes["smooth"]["learn_count"]) == ("ready", 5)
    assert (nodes["gate"]["state"], nodes["gate"]["ready"]) == ("held_back", True)
    # The step after the Gate keeps what it last reported.
    assert (nodes["change"]["state"], nodes["change"]["learn_count"]) == ("ready", 3)
    learn = snapshot["observation"]["passes"]["learn"]
    assert learn["gate"]["state"] == "held_back"
    assert learn["gate"]["output"] is None
    assert learn["gate"]["reason"] == "The condition does not hold for this observation"
    assert learn["change"] == {
        "input": None,
        "output": None,
        "state": "held_back",
        "reason": "Held back by a Gate before this step",
    }


def test_adaptive_monitoring_learns_and_scores_only_what_the_gate_lets_through():
    config = AnomalyDetectionConfig(
        pipeline=execution(GATE, ("scale", "adaptive.standard_scaler", {}))
    )
    service = AdaptiveStreamDetectionService(config)
    # The reference never receives what the Gate holds back.
    reference = AdaptiveStreamDetectionService(config)
    for index in range(1, 40):
        result = service.process_data_point(reading(index))
        phase = result.context["adaptive_stream"]["phase"]
        if not passes(index):
            assert phase == "held_back" and is_held_back(result.context)
            assert not result.should_persist
            assert result.raw_data == reading(index)
            continue
        expected = reference.process_data_point(reading(index))
        assert phase == expected.context["adaptive_stream"]["phase"]
        assert result.anomaly_score == expected.anomaly_score
    assert service.state == reference.state == AdaptiveStreamState.OPERATIONAL
    assert service.processed_count == 39
    assert service.warmup_count == reference.warmup_count
    state = PipelineRuntimeState.model_validate(service.get_pipeline_state())
    assert state.preparation is not None
    assert state.preparation.held_back == sum(not passes(i) for i in range(1, 40))
    assert state.preparation.ready
    checkpoint = pickle.loads(pickle.dumps(service.export_checkpoint()))
    restored = AdaptiveStreamDetectionService.from_checkpoint_data(checkpoint, config)
    later = range(40, 50)
    assert [restored.process_data_point(reading(i)).anomaly_score for i in later] == [
        service.process_data_point(reading(i)).anomaly_score for i in later
    ]


def test_a_static_baseline_collects_only_what_the_gate_lets_through():
    config = AnomalyDetectionConfig(
        pipeline=execution(
            GATE,
            ("scale", "static.standard_scaler", {}),
            strategy="static_baseline",
        ),
        checkpoint_interval=10000,
    )
    service = StaticConformalDetectionService(config)
    try:
        phases = [
            service.process_data_point(reading(index)).context["static_conformal"][
                "phase"
            ]
            for index in range(1, 11)
        ]
        assert phases == [
            "collecting" if passes(index) else "held_back" for index in range(1, 11)
        ]
        assert len(service.training_buffer) == sum(passes(i) for i in range(1, 11))
        assert service.processed_count == 10
        assert service.get_pipeline_state()["preparation"]["held_back"] == 4
    finally:
        service.shutdown()


def test_steps_over_the_whole_row_keep_no_state_to_admit():
    gated = ExecutionPlan(
        execution(
            GATE,
            ("power", "prepare.formula", {"expression": "a * b"}),
            ("mean", "prepare.aggregate", {}),
        )
    )
    assert estimate_resources(gated, 4096).prepare_state_bytes == 0
    assert PrepareStage(gated).export_state()["states"] == {}
