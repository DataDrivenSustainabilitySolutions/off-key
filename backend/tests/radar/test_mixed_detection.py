"""Detectors that learn in different ways, in one run.

A PyOD detector fitted once and an Aberrant detector that learns every
observation meet at the fixed split and alarm on its threshold.
"""

import math
import pickle

import pytest
from off_key_core.models.pipelines import derive_monitoring_config, validate_pipeline
from off_key_core.schemas.pipelines import PipelineDefinition
from off_key_core.schemas.radar import AdaptiveStreamConfig
from off_key_mqtt_radar.adaptive_detector import AdaptiveStreamState
from off_key_mqtt_radar.detector_services import detector_service_class
from off_key_mqtt_radar.mixed_detector import MixedDetectionService
from off_key_mqtt_radar.pipelines.plan import ExecutionPlan
from off_key_mqtt_radar.pipelines.resources import estimate_resources
from off_key_mqtt_radar.preflight import preflight

from tests.support.fused_pipeline import bound, reading

TRAINING, CALIBRATION = 30, 20
MAD = "detector:aberrant_moving_average_absolute_deviation"


def mixed_definition(policy="policy.quantile", fusion="max"):
    """Reading a scaled once into Isolation Forest, b scaled online into MAD."""
    return PipelineDefinition.model_validate(
        {
            "schema_version": 2,
            "input_slots": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            "nodes": [
                {"id": "input", "kind": "source", "component": "source.aligned"},
                {
                    "id": "only_a",
                    "kind": "transform",
                    "component": "features.select",
                    "params": {"features": ["a"]},
                },
                {
                    "id": "only_b",
                    "kind": "transform",
                    "component": "features.select",
                    "params": {"features": ["b"]},
                },
                {
                    "id": "fitted",
                    "kind": "transform",
                    "component": "static.standard_scaler",
                },
                {
                    "id": "online",
                    "kind": "transform",
                    "component": "adaptive.standard_scaler",
                },
                {
                    "id": "forest",
                    "kind": "detector",
                    "component": "detector:pyod_iforest",
                    "params": {"n_estimators": 10},
                },
                {
                    "id": "mad",
                    "kind": "detector",
                    "component": MAD,
                    "params": {"window_size": 10},
                },
                {
                    "id": "calibrate",
                    "kind": "calibration",
                    "component": "calibrate.fixed_split",
                    "params": {"fusion": fusion},
                },
                {
                    "id": "policy",
                    "kind": "policy",
                    "component": policy,
                    "params": {"quantile": 0.99} if policy == "policy.quantile" else {},
                },
                {"id": "output", "kind": "output", "component": "output.evidence"},
            ],
            "edges": [
                {"source": "input", "target": "only_a"},
                {"source": "input", "target": "only_b"},
                {"source": "only_a", "target": "fitted"},
                {"source": "only_b", "target": "online"},
                {"source": "fitted", "target": "forest"},
                {"source": "online", "target": "mad"},
                {"source": "forest", "target": "calibrate", "order": 0},
                {"source": "mad", "target": "calibrate", "order": 1},
                {"source": "calibrate", "target": "policy"},
                {"source": "policy", "target": "output"},
            ],
            "settings": {
                "training_window_size": TRAINING,
                "calibration_window_size": CALIBRATION,
                "seed": 7,
            },
        }
    )


def wave(index):
    return reading(math.sin(index / 5), math.cos(index / 7))


def feed(service, start, stop):
    results = []
    for index in range(start, stop):
        results.append(service.process_data_point(wave(index)))
        service.wait_for_background()
    return results


def test_detectors_that_learn_differently_compile_into_a_threshold_run():
    definition = mixed_definition()
    assert validate_pipeline(definition).valid

    monitoring = derive_monitoring_config(definition)
    assert isinstance(monitoring, AdaptiveStreamConfig)
    assert monitoring.model_type == "aberrant_moving_average_absolute_deviation"
    assert detector_service_class(bound(definition)) is MixedDetectionService


def test_the_martingale_still_refuses_a_detector_that_keeps_learning():
    issues = validate_pipeline(mixed_definition("policy.martingale")).issues

    assert ("calibration", "policy") in {(item.code, item.node_id) for item in issues}


def test_both_detectors_learn_calibrate_and_alarm_together():
    service = MixedDetectionService(bound(mixed_definition()))
    try:
        results = feed(service, 0, TRAINING + CALIBRATION + 40)
        phases = [item.context["adaptive_stream"]["phase"] for item in results]
        assert phases[:TRAINING] == ["warmup"] * TRAINING
        assert phases[TRAINING : TRAINING + CALIBRATION] == (
            ["calibration"] * CALIBRATION
        )
        # The replay waited for the fit, so nothing was left unscored.
        assert set(phases[TRAINING + CALIBRATION :]) == {"operational"}
        assert service.state == AdaptiveStreamState.OPERATIONAL
        assert service.batch.fitted and not service.batch.calibration
        assert len(service.calibration_scores) == CALIBRATION
        assert all(len(row) == 2 for row in service.calibration_scores)

        spike = service.process_data_point(reading(40.0, 40.0))
        context = spike.context["adaptive_stream"]
        assert spike.is_anomaly
        assert {item["detector_id"] for item in context["detectors"]} == {
            "forest",
            "mad",
        }
        assert service.get_pipeline_state()["batch_training"]["frozen"]
    finally:
        service.shutdown()


def test_the_run_reports_fitting_while_the_fit_is_pending():
    service = MixedDetectionService(bound(mixed_definition()))
    try:
        for index in range(TRAINING + CALIBRATION):
            service.process_data_point(wave(index))
        assert service.state == AdaptiveStreamState.FITTING
        assert service.get_model_info()["state"] == "fitting"
        service.wait_for_background()
        service.refresh_background_state()
        assert service.state == AdaptiveStreamState.OPERATIONAL
    finally:
        service.shutdown()


@pytest.mark.parametrize("stop", [TRAINING + CALIBRATION, TRAINING + CALIBRATION + 5])
def test_a_checkpoint_continues_exactly_where_it_left_off(stop):
    config = bound(mixed_definition())
    original = MixedDetectionService(config)
    try:
        for index in range(stop):
            original.process_data_point(wave(index))
        # A checkpoint taken while fitting refits after the restore.
        restored = MixedDetectionService.from_checkpoint_data(
            pickle.loads(pickle.dumps(original.export_checkpoint())), config
        )
        try:
            original.wait_for_background()
            restored.wait_for_background()
            expected = [
                (item.anomaly_score, item.is_anomaly)
                for item in feed(original, stop, stop + 25)
            ]
            actual = [
                (item.anomaly_score, item.is_anomaly)
                for item in feed(restored, stop, stop + 25)
            ]
            assert actual == expected
        finally:
            restored.shutdown()
    finally:
        original.shutdown()


def test_preflight_and_sizing_build_both_kinds_of_detector():
    config = bound(mixed_definition())
    report = preflight(config.pipeline)

    assert report["ok"]
    assert set(report["capabilities"]) == {"mad"}
    estimate = estimate_resources(ExecutionPlan(config.pipeline), 512)
    assert estimate.input_buffer_numeric_bytes > 0
    assert estimate.fusion_state_bytes > 0


def test_a_dojo_replay_runs_both_kinds_of_detector_end_to_end():
    from datetime import UTC, datetime

    from off_key_core.models.dojo_runs import BoundSeries, bind_dataset, series_topic
    from off_key_core.models.pipelines import compile_pipeline
    from off_key_core.schemas.dojo import RunAlignment
    from off_key_mqtt_radar.dojo.replay import Replay, detection_config

    definition = compile_pipeline(mixed_definition()).definition
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
    run = Replay(detection_config(execution, RunAlignment(), 16384))
    start = datetime(2026, 3, 1, tzinfo=UTC).timestamp()
    rows = []
    try:
        for index in range(TRAINING + CALIBRATION + 30):
            values = (40.0, 40.0) if index == TRAINING + CALIBRATION + 20 else None
            for slot in range(2):
                value = values[slot] if values else wave(index)[list(wave(index))[slot]]
                row = run.step(series_topic(slot), start + 60 * index, value)
                if row is not None:
                    rows.append(row)
    finally:
        run.close()

    assert [row.sequence for row in rows] == list(range(1, TRAINING + CALIBRATION + 31))
    assert rows[-1].phase == "operational"
    scored = [row for row in rows if row.score is not None]
    assert len(scored) == 30 and all(row.threshold is not None for row in scored)
    assert rows[TRAINING + CALIBRATION + 20].alarm
