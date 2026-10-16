"""Real adaptive graphs, lifecycle ordering, restoration and failure boundaries."""

from __future__ import annotations

import pickle
from datetime import UTC, datetime

import pytest
from off_key_core.models.pipelines import compile_pipeline, execution_fingerprint
from off_key_core.schemas.pipelines import (
    BoundInput,
    PipelineDefinition,
    PipelineExecutionConfig,
)
from off_key_mqtt_radar.adaptive_detector import AdaptiveStreamState
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig
from off_key_mqtt_radar.execution_errors import (
    FatalExecutionError,
    ObservationRejected,
)
from off_key_mqtt_radar.pipelines.adapters import adaptive_graph
from off_key_mqtt_radar.pipelines.adaptive import AdaptivePipelineDetectionService
from off_key_mqtt_radar.pipelines.diagnostics import DiagnosticLimits
from off_key_mqtt_radar.pipelines.plan import ExecutionPlan


def _config(*, model="aberrant_moving_covariance", branched=True, clipped=False):
    slots = ["a", "b", "temperature"] if branched else ["a"]
    nodes = [{"id": "input", "kind": "source", "component": "source.aligned"}]
    edges = []
    if branched:
        nodes.extend(
            [
                {
                    "id": "selected",
                    "kind": "transform",
                    "component": "features.select",
                    "params": {"features": ["a", "b"]},
                },
                {
                    "id": "scaled",
                    "kind": "transform",
                    "component": "adaptive.min_max_scaler"
                    if clipped
                    else "adaptive.standard_scaler",
                    "params": {"clip": True} if clipped else {},
                },
                {
                    "id": "raw",
                    "kind": "transform",
                    "component": "features.select",
                    "params": {"features": ["temperature"]},
                },
                {"id": "joined", "kind": "merge", "component": "features.merge"},
            ]
        )
        edges.extend(
            [
                {"source": "input", "target": "selected"},
                {"source": "selected", "target": "scaled"},
                {"source": "input", "target": "raw"},
                {"source": "raw", "target": "joined", "order": 1},
            ]
        )
        if clipped:
            edges.append({"source": "scaled", "target": "joined", "order": 0})
        else:
            nodes.append(
                {
                    "id": "pca",
                    "kind": "transform",
                    "component": "adaptive.uncentered_pca",
                    "params": {"n_components": 1, "n0": 3},
                }
            )
            edges.extend(
                [
                    {"source": "scaled", "target": "pca"},
                    {"source": "pca", "target": "joined", "order": 0},
                ]
            )
    params = (
        {"n_trees": 1, "height": 2, "window_size": 2, "seed": 1}
        if model == "aberrant_half_space_trees"
        else {"window_size": 5}
    )
    nodes.extend(
        [
            {
                "id": "model",
                "kind": "detector",
                "component": f"detector:{model}",
                "params": params,
            },
            {
                "id": "policy",
                "kind": "policy",
                "component": "policy.quantile",
                "params": {"quantile": 1.0},
            },
            {"id": "output", "kind": "output", "component": "output.evidence"},
        ]
    )
    edges.extend(
        [
            {"source": "joined" if branched else "input", "target": "model"},
            {"source": "model", "target": "policy"},
            {"source": "policy", "target": "output"},
        ]
    )
    definition = compile_pipeline(
        PipelineDefinition.model_validate(
            {
                "strategy": "adaptive_stream",
                "input_slots": [{"id": key, "label": key.title()} for key in slots],
                "nodes": nodes,
                "edges": edges,
                "settings": {"training_window_size": 2, "calibration_window_size": 2},
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
        for slot in slots
    ]
    execution = PipelineExecutionConfig(
        definition=definition,
        bindings=bindings,
        run_id="run",
        revision_id="revision",
        fingerprint=execution_fingerprint(definition, bindings),
    )
    return AnomalyDetectionConfig(pipeline=execution, checkpoint_interval=1_000_000)


def _point(index):
    return {
        "reading_a": float(index),
        "reading_b": float(index**2),
        "reading_temperature": 20.0 + index,
    }


def test_branched_monitor_matches_standalone_numeric_reference():
    config = _config()
    service = AdaptivePipelineDetectionService(config, automatic_checkpoints=False)
    reference, _ = adaptive_graph(ExecutionPlan(config.pipeline))
    states = []
    for index in range(1, 9):
        data = _point(index)
        bound = service.plan.bind(data)
        expected = (
            reference.score_one(bound)
            if reference.readiness.ready and reference.model_updates >= 2
            else None
        )
        reference.learn_one(bound)
        result = service.process_data_point(data)
        states.append(service.state)
        if expected is not None:
            assert result.anomaly_score == pytest.approx(expected)
        assert result.raw_data == data
        assert service.pipeline.model_updates == reference.model_updates
    assert states[:4] == [AdaptiveStreamState.WARMUP] * 3 + [
        AdaptiveStreamState.CALIBRATING
    ]
    assert states[5] == AdaptiveStreamState.OPERATIONAL
    assert service.warmup_count == 2
    assert service.calibration_count == 2
    assert service.operational_count == 2
    assert result.should_persist
    assert set(result.processed_features) == {"pca.component_1", "temperature"}


@pytest.mark.parametrize("processed", [2, 5, 7])
def test_graph_checkpoints_restore_every_learning_phase(processed):
    config = _config()
    original = AdaptivePipelineDetectionService(config, automatic_checkpoints=False)
    for index in range(1, processed + 1):
        original.process_data_point(_point(index))
    checkpoint = pickle.loads(pickle.dumps(original.export_checkpoint()))
    restored = AdaptivePipelineDetectionService.from_checkpoint_data(
        checkpoint, config, automatic_checkpoints=False
    )
    assert restored.pipeline.observer is not None
    for index in range(processed + 1, 10):
        expected = original.process_data_point(_point(index))
        actual = restored.process_data_point(_point(index))
        assert actual.anomaly_score == pytest.approx(expected.anomaly_score)
        assert actual.is_anomaly == expected.is_anomaly
        assert restored.pipeline.model_updates == original.pipeline.model_updates
    assert restored.state == original.state == AdaptiveStreamState.OPERATIONAL


@pytest.mark.parametrize(
    "invalid",
    [
        {},
        {"wrong": 1.0},
        {"reading_a": float("nan"), "reading_b": 1.0, "reading_temperature": 20.0},
    ],
)
def test_invalid_observations_do_not_mutate_or_fail_graph(invalid):
    service = AdaptivePipelineDetectionService(_config(), automatic_checkpoints=False)
    before = pickle.dumps(service.pipeline)
    with pytest.raises(ObservationRejected):
        service.process_data_point(invalid)
    assert pickle.dumps(service.pipeline) == before
    assert service.processed_count == 0
    assert service.state == AdaptiveStreamState.WARMUP
    assert not service._execution_failed
    service.process_data_point(_point(1))
    assert service.processed_count == 1


def test_raw_unit_interval_rejection_precedes_all_branch_learning():
    service = AdaptivePipelineDetectionService(
        _config(model="aberrant_half_space_trees", clipped=True),
        automatic_checkpoints=False,
    )
    valid = {"reading_a": 100.0, "reading_b": -50.0, "reading_temperature": 0.5}
    service.process_data_point(valid)
    previous = pickle.dumps(service.pipeline)
    with pytest.raises(ObservationRejected, match="temperature"):
        service.process_data_point({**valid, "reading_temperature": 1.5})
    assert pickle.dumps(service.pipeline) == previous
    assert service.processed_count == 1
    service.process_data_point(valid)
    assert service.state == AdaptiveStreamState.CALIBRATING


@pytest.mark.parametrize(
    "model,ignored",
    [
        ("aberrant_moving_geometric_average", [0.0, -1.0]),
        ("aberrant_moving_harmonic_average", [0.0, 0.0]),
    ],
)
def test_retained_history_blocks_calibration_until_reference_exists(model, ignored):
    service = AdaptivePipelineDetectionService(
        _config(model=model, branched=False), automatic_checkpoints=False
    )
    for value in ignored:
        service.process_data_point({"reading_a": value})
    assert service.warmup_count == 2
    assert service.state == AdaptiveStreamState.WARMUP
    assert service.calibration_count == 0
    service.process_data_point({"reading_a": 2.0})
    if "geometric" in model:
        assert service.state == AdaptiveStreamState.WARMUP
        service.process_data_point({"reading_a": 3.0})
    assert service.state == AdaptiveStreamState.CALIBRATING
    assert service.calibration_count == 0


def test_execution_failure_stops_model_and_blocks_checkpoint():
    service = AdaptivePipelineDetectionService(
        _config(model="aberrant_moving_geometric_average", branched=False),
        automatic_checkpoints=False,
    )
    for value in (1.0, 2.0, 3.0, 4.0):
        service.process_data_point({"reading_a": value})
    assert service.state == AdaptiveStreamState.OPERATIONAL
    with pytest.raises(FatalExecutionError, match="positive"):
        service.process_data_point({"reading_a": 0.0})
    count = service.pipeline.model_updates
    assert service.state == AdaptiveStreamState.FAILED
    with pytest.raises(FatalExecutionError):
        service.export_checkpoint()
    with pytest.raises(FatalExecutionError):
        service.process_data_point({"reading_a": 5.0})
    assert service.pipeline.model_updates == count
    snapshot = service.get_pipeline_state()
    assert snapshot["nodes"]["model"]["state"] == "failed"


def test_live_values_come_from_real_score_pass_with_original_metadata():
    service = AdaptivePipelineDetectionService(_config(), automatic_checkpoints=False)
    service.diagnostics.limits = DiagnosticLimits(sample_interval_seconds=1e-12)
    for index in range(1, 8):
        result = service.process_data_point(_point(index))
    timestamp = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
    service.attach_observation_metadata(timestamp, {"reading_a": timestamp.timestamp()})
    snapshot = service.get_pipeline_state()
    observation = snapshot["observation"]
    assert observation["sequence_number"] == 7
    assert observation["timestamp"] == timestamp.isoformat()
    assert observation["input_timestamps"]["reading_a"] == timestamp.isoformat()
    assert observation["passes"]["score"]["model"]["input"] == result.processed_features
    assert observation["passes"]["score"]["model"]["output"] == result.anomaly_score
    assert snapshot["nodes"]["model"]["learn_count"] == 5
    assert "observation" not in service.get_model_info()


def test_diagnostic_failure_does_not_replace_inference_result(monkeypatch):
    service = AdaptivePipelineDetectionService(_config(), automatic_checkpoints=False)

    def broken(*args):
        raise RuntimeError("diagnostics failed")

    monkeypatch.setattr(service.diagnostics, "begin", broken)
    monkeypatch.setattr(service.diagnostics, "finish", broken)
    for index in range(1, 8):
        result = service.process_data_point(_point(index))
    assert result.should_persist
    assert service.state == AdaptiveStreamState.OPERATIONAL
    assert service.diagnostics.errors >= 14
