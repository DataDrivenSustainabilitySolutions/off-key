"""Real adaptive graphs, lifecycle ordering, restoration and failure boundaries."""

from __future__ import annotations

import pickle
from datetime import UTC, datetime

import pytest
from off_key_mqtt_radar.adaptive_detector import AdaptiveStreamState
from off_key_mqtt_radar.execution_errors import (
    FatalExecutionError,
    ObservationRejected,
)
from off_key_mqtt_radar.pipelines.adapters import adaptive_graph
from off_key_mqtt_radar.pipelines.adaptive import AdaptivePipelineDetectionService
from off_key_mqtt_radar.pipelines.diagnostics import DiagnosticLimits
from off_key_mqtt_radar.pipelines.plan import ExecutionPlan

from tests.support.adaptive_pipeline import adaptive_pipeline_config

pytestmark = pytest.mark.radar_integration


def _point(index):
    return {
        "reading_a": float(index),
        "reading_b": float(index**2),
        "reading_temperature": 20.0 + index,
    }


@pytest.mark.parametrize(
    ("model", "params", "required"),
    [
        ("aberrant_moving_geometric_average", {"window_size": 2}, 2),
        (
            "aberrant_moving_geometric_average",
            {"window_size": 3, "absoluteValues": True},
            3,
        ),
        ("aberrant_moving_harmonic_average", {"window_size": 1}, 1),
    ],
)
def test_smallest_admissible_retained_windows_reach_real_runtime_readiness(
    model, params, required
):
    config = adaptive_pipeline_config(model=model, branched=False, model_params=params)
    service = AdaptivePipelineDetectionService(config)
    for index in range(1, 12):
        result = service.process_data_point({"reading_a": float(index)})
    state = service.get_pipeline_state()["nodes"]["model"]
    assert state["readiness_required"] == required
    assert state["ready"]
    assert service.state == AdaptiveStreamState.OPERATIONAL
    assert result.should_persist


def test_branched_monitor_matches_standalone_numeric_reference():
    config = adaptive_pipeline_config()
    service = AdaptivePipelineDetectionService(config)
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


def test_real_pca_readiness_reports_progress_and_model_dependency_chain():
    service = AdaptivePipelineDetectionService(adaptive_pipeline_config())
    initial = service.get_pipeline_state()["nodes"]
    assert initial["pca"]["readiness_observed"] == 0
    assert initial["pca"]["readiness_required"] == 3
    assert initial["pca"]["blocked_by"] == ["scaled"]
    assert not initial["pca"]["ready"]
    assert initial["joined"]["blocked_by"] == ["pca"]
    assert initial["model"]["blocked_by"] == ["joined"]
    assert initial["model"]["learned_updates"] == 0
    service.process_data_point(_point(1))
    first = service.get_pipeline_state()["nodes"]
    assert first["pca"]["learned_updates"] == first["pca"]["learn_count"] == 1
    assert first["pca"]["readiness_observed"] == 1
    assert first["pca"]["readiness_required"] == 3
    assert first["pca"]["state"] == "initializing"
    assert first["model"]["state"] == "waiting_for_dependency"
    assert first["model"]["readiness_reason"] == "Waiting for feature graph"
    for index in (2, 3):
        service.process_data_point(_point(index))
    projected = service.get_pipeline_state()["nodes"]
    assert projected["pca"]["ready"]
    assert projected["pca"]["readiness_observed"] == 3
    assert projected["model"]["blocked_by"] == []
    assert projected["model"]["learned_updates"] == 1
    assert not projected["model"]["ready"]
    service.process_data_point(_point(4))
    ready = service.get_pipeline_state()["nodes"]
    assert ready["model"]["state"] == "ready"
    assert ready["model"]["ready"]
    assert ready["model"]["learned_updates"] == ready["model"]["learn_count"] == 2
    assert ready["model"]["readiness_observed"] >= ready["model"]["readiness_required"]
    # Snapshots stay detached while the live committed counts continue advancing.
    assert first["pca"]["readiness_observed"] == 1
    assert first["model"]["blocked_by"] == ["joined"]


@pytest.mark.parametrize("processed", [2, 5, 7])
def test_graph_checkpoints_restore_every_learning_phase(processed):
    config = adaptive_pipeline_config()
    original = AdaptivePipelineDetectionService(config)
    for index in range(1, processed + 1):
        original.process_data_point(_point(index))
    checkpoint = pickle.loads(pickle.dumps(original.export_checkpoint()))
    restored = AdaptivePipelineDetectionService.from_checkpoint_data(checkpoint, config)
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
    service = AdaptivePipelineDetectionService(adaptive_pipeline_config())
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
        adaptive_pipeline_config(model="aberrant_half_space_trees", clipped=True),
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
        adaptive_pipeline_config(model=model, branched=False)
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
        adaptive_pipeline_config(
            model="aberrant_moving_geometric_average", branched=False
        ),
    )
    for value in (1.0, 2.0, 3.0, 4.0):
        service.process_data_point({"reading_a": value})
    assert service.state == AdaptiveStreamState.OPERATIONAL
    with pytest.raises(FatalExecutionError, match="positive") as failure:
        service.process_data_point({"reading_a": 0.0})
    assert failure.value.node_id == "model"
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
    service = AdaptivePipelineDetectionService(adaptive_pipeline_config())
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
    service = AdaptivePipelineDetectionService(adaptive_pipeline_config())

    def broken(*args):
        raise RuntimeError("diagnostics failed")

    monkeypatch.setattr(service.diagnostics, "begin", broken)
    monkeypatch.setattr(service.diagnostics, "finish", broken)
    for index in range(1, 8):
        result = service.process_data_point(_point(index))
    assert result.should_persist
    assert service.state == AdaptiveStreamState.OPERATIONAL
    assert service.diagnostics.errors >= 14
