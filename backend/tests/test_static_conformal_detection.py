"""Unit tests for static chronological conformal RADAR monitoring."""

import concurrent.futures
import hashlib
import json
import pickle

import pytest
from off_key_core.schemas.radar import StaticBaselineConfig, StaticMartingaleConfig
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig
from off_key_mqtt_radar.config.runtime import clear_radar_runtime_settings_cache
from off_key_mqtt_radar.detector import (
    RestartedMartingaleAlarmController,
    StaticConformalDetectionService,
    StaticConformalState,
)


class FakeConformalDetector:
    def __init__(self, p_value: float = 0.001):
        self.p_value = p_value

    def compute_p_values(self, _matrix):
        return [self.p_value]


class FakeLegacyController:
    num_test = 13


class ControlledExecutor:
    def __init__(self):
        self.future: concurrent.futures.Future = concurrent.futures.Future()

    def submit(self, *_args, **_kwargs):
        return self.future


class InlineExecutor:
    def submit(self, func, *args, **kwargs):
        future: concurrent.futures.Future = concurrent.futures.Future()
        try:
            future.set_result(func(*args, **kwargs))
        except Exception as exc:
            future.set_exception(exc)
        return future

    def shutdown(self, *_args, **_kwargs):
        return None


def _legacy_fdr_static_signature(config: AnomalyDetectionConfig) -> str:
    static_payload = config.static_baseline_config.model_dump(
        exclude={"calibration_window_size", "martingale_config"},
        exclude_none=True,
    )
    payload = {
        "strategy": "static_baseline",
        "model_type": str(static_payload.get("model_type", config.model_type)),
        "model_params": static_payload.get("model_params", config.model_params or {}),
        "static_baseline_config": static_payload,
        "subscription_topics": sorted(
            str(topic) for topic in (config.subscription_topics or [])
        ),
        "sensor_key_strategy": config.sensor_key_strategy,
        "alignment_mode": config.alignment_mode,
    }
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()


def _static_config(
    monkeypatch,
    *,
    martingale_config: StaticMartingaleConfig | None = None,
    model_params: dict | None = None,
    model_type: str = "pyod_iforest",
    training_window_size: int = 20,
    calibration_window_size: int = 5,
) -> AnomalyDetectionConfig:
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

    model_params = model_params or {"n_estimators": 100}
    return AnomalyDetectionConfig(
        strategy="static_baseline",
        model_type=model_type,
        model_params=model_params,
        preprocessing_steps=[],
        static_baseline_config=StaticBaselineConfig(
            model_type=model_type,
            model_params=model_params,
            training_window_size=training_window_size,
            calibration_window_size=calibration_window_size,
            martingale_config=martingale_config
            or StaticMartingaleConfig(alpha=0.9, epsilon=0.5),
        ),
        checkpoint_interval=100000,
    )


def test_static_conformal_collects_calibrates_trains_then_detects(monkeypatch):
    config = _static_config(monkeypatch)
    service = StaticConformalDetectionService(config)
    executor = ControlledExecutor()
    service._training_executor = executor

    for index in range(19):
        result = service.process_data_point({"L1": float(index), "L2": 1.0})
        static_context = result.context["static_conformal"]
        assert static_context["phase"] == "collecting"
        assert "p_value" not in static_context

    calibration_started = service.process_data_point({"L1": 20.0, "L2": 1.0})
    assert calibration_started.context["static_conformal"]["phase"] == "calibrating"
    assert service.state == StaticConformalState.CALIBRATING

    for index in range(4):
        result = service.process_data_point({"L1": 21.0 + index, "L2": 1.0})
        assert result.context["static_conformal"]["phase"] == "calibrating"

    training_started = service.process_data_point({"L1": 25.0, "L2": 1.0})
    assert training_started.context["static_conformal"]["phase"] == "training_started"
    assert service.state == StaticConformalState.TRAINING

    discarded = service.process_data_point({"L1": 26.0, "L2": 1.0})
    assert discarded.context["static_conformal"]["phase"] == "training_discarded"
    assert service.discarded_during_training_count == 1

    executor.future.set_result(
        (FakeConformalDetector(p_value=0.000001), service._create_alarm_controller())
    )
    anomaly = service.process_data_point({"L1": 100.0, "L2": 9.0})
    static_context = anomaly.context["static_conformal"]

    assert service.state == StaticConformalState.READY
    assert anomaly.is_anomaly is True
    assert anomaly.anomaly_score == 0.000001
    assert static_context["p_value"] == 0.000001
    assert static_context["martingale_method"] == "power"
    assert static_context["alarm_fired"] is True
    assert static_context["alarm_count"] == 1
    assert static_context["tested_count"] == 1


def test_static_conformal_rejects_schema_mismatch_after_schema_freeze(monkeypatch):
    config = _static_config(monkeypatch)
    service = StaticConformalDetectionService(config)

    service.conformal_detector = FakeConformalDetector()
    service.alarm_controller = service._create_alarm_controller()
    service.feature_keys = ["L1", "L2"]
    service.state = StaticConformalState.READY

    result = service.process_data_point({"L1": 1.0, "L3": 2.0})

    assert result.is_anomaly is False
    assert result.context["static_conformal"]["phase"] == "schema_mismatch"
    assert "schema_error" in result.context["static_conformal"]


def test_static_conformal_martingale_ignores_non_crossing_p_values(monkeypatch):
    config = _static_config(monkeypatch)
    service = StaticConformalDetectionService(config)
    service.conformal_detector = FakeConformalDetector(p_value=1.0)
    service.alarm_controller = service._create_alarm_controller()
    service.feature_keys = ["L1", "L2"]
    service.state = StaticConformalState.READY

    result = service.process_data_point({"L1": 1.0, "L2": 2.0})
    static_context = result.context["static_conformal"]

    assert result.is_anomaly is False
    assert result.severity == "low"
    assert static_context["alarm_fired"] is False
    assert static_context["tested_count"] == 1


def test_restarted_martingale_controller_alpha_spends_after_alarm():
    controller = RestartedMartingaleAlarmController(alpha=0.9, epsilon=0.5)

    first_threshold = controller.restarted_ville_threshold
    result = controller.update(0.000001)

    assert result["alarm_fired"] is True
    assert result["alarm_count"] == 1
    assert controller.alarm_count == 1
    assert controller.tested_count == 1
    assert controller.restarted_ville_threshold > first_threshold


def test_static_conformal_real_pyod_nonconform_training_reaches_ready(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("RADAR_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv("SERVICE_ID", "static-conformal-test")
    clear_radar_runtime_settings_cache()
    config = _static_config(
        monkeypatch,
        martingale_config=StaticMartingaleConfig(alpha=0.01, epsilon=0.5),
        model_params={
            "contamination": 0.1,
        },
        model_type="pyod_hbos",
    )
    service = StaticConformalDetectionService(config)
    service._training_executor.shutdown(wait=False, cancel_futures=True)
    service._training_executor = InlineExecutor()

    try:
        for index in range(20):
            result = service.process_data_point(
                {"L1": float(index), "L2": float(index % 4)}
            )

        assert result.context["static_conformal"]["phase"] == "calibrating"
        assert service.state == StaticConformalState.CALIBRATING

        for index in range(5):
            result = service.process_data_point(
                {"L1": float(20 + index), "L2": float(index % 4)}
            )

        assert result.context["static_conformal"]["phase"] == "training_started"
        assert service.state == StaticConformalState.TRAINING

        service._complete_training_if_ready()

        assert service.state == StaticConformalState.READY, service.training_error

        result = service.process_data_point({"L1": 100.0, "L2": 20.0})
        static_context = result.context["static_conformal"]
        assert static_context["phase"] == "ready"
        assert static_context["martingale_method"] == "power"
        assert 0.0 <= static_context["p_value"] <= 1.0
        assert 0.0 <= result.anomaly_score <= 1.0
    finally:
        service.shutdown()
        clear_radar_runtime_settings_cache()


def test_static_conformal_restores_ready_checkpoint(monkeypatch, tmp_path):
    config = _static_config(monkeypatch)
    alarm_controller = RestartedMartingaleAlarmController(
        alpha=0.9, epsilon=0.5, alarm_count=2, tested_count=7
    )
    checkpoint = {
        "strategy": "static_baseline",
        "static_state": "ready",
        "training_buffer": [],
        "calibration_buffer": [],
        "feature_keys": ["L1", "L2"],
        "conformal_detector": FakeConformalDetector(),
        "alarm_controller": alarm_controller,
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
    assert restored.alarm_controller.alarm_count == 2
    assert restored.alarm_controller.tested_count == 7


def test_static_conformal_legacy_checkpoint_gets_fresh_alarm_controller(
    monkeypatch,
    tmp_path,
):
    config = _static_config(monkeypatch)
    checkpoint = {
        "strategy": "static_baseline",
        "static_state": "ready",
        "training_buffer": [],
        "feature_keys": ["L1", "L2"],
        "conformal_detector": FakeConformalDetector(),
        "fdr_controller": FakeLegacyController(),
        "processed_count": 42,
        "anomaly_count": 3,
        "schema_signature": _legacy_fdr_static_signature(config),
    }
    checkpoint_path = tmp_path / "legacy-static.pkl"
    checkpoint_path.write_bytes(pickle.dumps(checkpoint))

    restored = StaticConformalDetectionService.from_checkpoint(
        str(checkpoint_path), config
    )

    assert restored.state == StaticConformalState.READY
    assert isinstance(restored.alarm_controller, RestartedMartingaleAlarmController)
    assert restored.alarm_controller.tested_count == 13


def test_static_conformal_legacy_checkpoint_rejects_signature_mismatch(
    monkeypatch,
    tmp_path,
):
    config = _static_config(monkeypatch)
    checkpoint = {
        "strategy": "static_baseline",
        "static_state": "ready",
        "training_buffer": [],
        "feature_keys": ["L1", "L2"],
        "conformal_detector": FakeConformalDetector(),
        "fdr_controller": FakeLegacyController(),
        "processed_count": 42,
        "anomaly_count": 3,
        "schema_signature": "different-signature",
    }
    checkpoint_path = tmp_path / "legacy-static-mismatch.pkl"
    checkpoint_path.write_bytes(pickle.dumps(checkpoint))

    with pytest.raises(ValueError, match="schema signature"):
        StaticConformalDetectionService.from_checkpoint(str(checkpoint_path), config)


def test_static_conformal_uses_static_config_model_params(monkeypatch):
    from off_key_mqtt_radar import tactic_client

    validated_calls = []
    monkeypatch.setattr(
        tactic_client,
        "validate_model_params",
        lambda model_type, params=None: validated_calls.append(
            (model_type, params or {})
        )
        or params
        or {},
    )
    monkeypatch.setattr(
        tactic_client,
        "validate_preprocessing_steps",
        lambda steps=None: steps or [],
    )
    config = AnomalyDetectionConfig(
        strategy="static_baseline",
        model_type="pyod_iforest",
        model_params={},
        static_baseline_config=StaticBaselineConfig(
            model_type="pyod_knn",
            model_params={"n_neighbors": 7, "contamination": 0.08},
            training_window_size=20,
            calibration_window_size=5,
        ),
        checkpoint_interval=100000,
    )
    service = StaticConformalDetectionService(config)
    captured = {}

    def fake_instantiate(model_type, params):
        captured["model_type"] = model_type
        captured["params"] = params
        return object()

    monkeypatch.setattr(service, "_instantiate_pyod_detector", fake_instantiate)

    service._create_pyod_detector()

    assert validated_calls[0] == (
        "pyod_knn",
        {"n_neighbors": 7, "contamination": 0.08},
    )
    assert captured["model_type"] == "pyod_knn"
    assert captured["params"]["n_neighbors"] == 7
    assert captured["params"]["contamination"] == 0.08
