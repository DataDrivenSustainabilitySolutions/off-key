"""Unit tests for static conformal RADAR detector lifecycle."""

import concurrent.futures
import pickle

from off_key_core.schemas.radar import FdrConfig, StaticBaselineConfig
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig
from off_key_mqtt_radar.detector import (
    StaticConformalDetectionService,
    StaticConformalState,
)


class FakeConformalDetector:
    def __init__(self, p_value: float = 0.001):
        self.p_value = p_value

    def compute_p_values(self, _matrix):
        return [self.p_value]


class FakeSaffron:
    def __init__(self):
        self.alpha = 0.05
        self.num_test = 0

    def test_one(self, p_value: float) -> bool:
        self.num_test += 1
        return p_value <= 0.01


class ControlledExecutor:
    def __init__(self):
        self.future: concurrent.futures.Future = concurrent.futures.Future()

    def submit(self, *_args, **_kwargs):
        return self.future


def _static_config(monkeypatch) -> AnomalyDetectionConfig:
    from off_key_mqtt_radar import tactic_client

    monkeypatch.setattr(
        tactic_client,
        "validate_model_params",
        lambda _model_type, params=None: params or {},
    )
    monkeypatch.setattr(
        tactic_client,
        "validate_preprocessing_steps",
        lambda steps=None: steps or [],
    )

    return AnomalyDetectionConfig(
        strategy="static_baseline",
        model_type="pyod_iforest",
        model_params={"n_estimators": 100},
        preprocessing_steps=[],
        static_baseline_config=StaticBaselineConfig(
            model_type="pyod_iforest",
            model_params={"n_estimators": 100},
            training_window_size=20,
            calibration_fraction=0.25,
            fdr_config=FdrConfig(alpha=0.05, wealth=0.025, lambda_=0.5),
        ),
        checkpoint_interval=100000,
    )


def test_static_conformal_collects_trains_discards_then_detects(monkeypatch):
    config = _static_config(monkeypatch)
    service = StaticConformalDetectionService(config)
    executor = ControlledExecutor()
    service._training_executor = executor

    for index in range(19):
        result = service.process_data_point({"L1": float(index), "L2": 1.0})
        assert result.context["static_conformal"]["phase"] == "collecting"

    training_started = service.process_data_point({"L1": 20.0, "L2": 1.0})
    assert training_started.context["static_conformal"]["phase"] == "training_started"
    assert service.state == StaticConformalState.TRAINING

    discarded = service.process_data_point({"L1": 21.0, "L2": 1.0})
    assert discarded.context["static_conformal"]["phase"] == "training_discarded"
    assert service.discarded_during_training_count == 1

    executor.future.set_result((FakeConformalDetector(), FakeSaffron()))
    anomaly = service.process_data_point({"L1": 100.0, "L2": 9.0})

    assert anomaly.is_anomaly is True
    assert anomaly.anomaly_score == 0.001
    assert anomaly.context["static_conformal"]["p_value"] == 0.001
    assert anomaly.context["static_conformal"]["fdr_method"] == "saffron"
    assert service.state == StaticConformalState.READY


def test_static_conformal_rejects_schema_mismatch_after_schema_freeze(monkeypatch):
    config = _static_config(monkeypatch)
    service = StaticConformalDetectionService(config)

    service.conformal_detector = FakeConformalDetector()
    service.fdr_controller = FakeSaffron()
    service.feature_keys = ["L1", "L2"]
    service.state = StaticConformalState.READY

    result = service.process_data_point({"L1": 1.0, "L3": 2.0})

    assert result.is_anomaly is False
    assert result.context["static_conformal"]["phase"] == "schema_mismatch"
    assert "schema_error" in result.context["static_conformal"]


def test_static_conformal_restores_ready_checkpoint(monkeypatch, tmp_path):
    config = _static_config(monkeypatch)
    checkpoint = {
        "strategy": "static_baseline",
        "static_state": "ready",
        "training_buffer": [],
        "feature_keys": ["L1", "L2"],
        "conformal_detector": FakeConformalDetector(),
        "fdr_controller": FakeSaffron(),
        "processed_count": 42,
        "anomaly_count": 3,
        "discarded_during_training_count": 2,
        "schema_mismatch_count": 1,
        "training_error": None,
        "schema_signature": (
            StaticConformalDetectionService._build_schema_signature_from_config(config)
        ),
    }
    checkpoint_path = tmp_path / "static.pkl"
    checkpoint_path.write_bytes(pickle.dumps(checkpoint))

    restored = StaticConformalDetectionService.from_checkpoint(
        str(checkpoint_path), config
    )

    assert restored.state == StaticConformalState.READY
    assert restored.processed_count == 42
    assert restored.feature_keys == ["L1", "L2"]
