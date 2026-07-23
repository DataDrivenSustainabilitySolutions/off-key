"""Unit tests for static chronological conformal RADAR monitoring."""

import concurrent.futures
import pickle

import pytest
from off_key_core.schemas.radar import StaticBaselineConfig, StaticMartingaleConfig
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig
from off_key_mqtt_radar.config.runtime import clear_radar_runtime_settings_cache
from off_key_mqtt_radar.detector import (
    ResilientAnomalyDetector,
    RestartedMartingaleAlarmController,
    StaticConformalDetectionService,
    StaticConformalState,
)


class FakeConformalDetector:
    def __init__(self, p_value: float = 0.001):
        self.p_value = p_value

    def compute_p_values(self, _matrix):
        return [self.p_value]


class FakeMalformedConformalDetector:
    def __init__(self, p_values):
        self.p_values = p_values

    def compute_p_values(self, _matrix):
        return self.p_values


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
    model_params = model_params or {"n_estimators": 100}
    return AnomalyDetectionConfig(
        strategy="static_baseline",
        model_type=model_type,
        model_params=model_params,
        static_baseline_config=StaticBaselineConfig(
            model_type=model_type,
            model_params=model_params,
            training_window_size=training_window_size,
            calibration_window_size=calibration_window_size,
            martingale_config=martingale_config or StaticMartingaleConfig(epsilon=0.5),
        ),
        checkpoint_interval=100000,
    )


def test_static_conformal_collects_calibrates_trains_then_detects(monkeypatch):
    config = _static_config(monkeypatch)
    service = StaticConformalDetectionService(config)
    service._checkpoint_model = lambda: None
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


@pytest.mark.parametrize(
    "p_values",
    [[], [0.1, 0.2], [float("nan")], [-0.1], [1.1]],
)
def test_static_conformal_rejects_malformed_p_value_output(monkeypatch, p_values):
    service = StaticConformalDetectionService(_static_config(monkeypatch))
    service.conformal_detector = FakeMalformedConformalDetector(p_values)

    with pytest.raises(ValueError, match="p-value"):
        service._compute_p_value([1.0, 2.0])


def test_static_health_poll_completes_finished_background_training(monkeypatch):
    service = StaticConformalDetectionService(_static_config(monkeypatch))
    executor = ControlledExecutor()
    service._training_executor = executor
    service._checkpoint_model = lambda: None
    service.state = StaticConformalState.TRAINING
    service._training_future = executor.future
    executor.future.set_result(
        (FakeConformalDetector(p_value=0.5), service._create_alarm_controller())
    )

    health_info = ResilientAnomalyDetector(service).get_health_info()

    assert health_info["primary_service_stats"]["state"] == "ready"
    assert service.state == StaticConformalState.READY
    assert service._training_future is None


def test_restarted_martingale_controller_uses_native_fixed_mixture():
    controller = RestartedMartingaleAlarmController(epsilon=0.5)

    result = controller.update(0.000001)
    repeated = controller.update(0.000001)

    assert result["alarm_fired"] is True
    assert result["alarm_count"] == 1
    assert result["e_value"] == pytest.approx(500.0)
    assert result["restarted_ville_threshold"] == 100.0
    assert repeated["alarm_fired"] is False
    assert repeated["alarm_active"] is True
    assert controller.alarm_count == 1
    assert controller.tested_count == 2
    assert controller.restarted_ville_threshold == 100.0


def test_restarted_martingale_controller_serializes_infinite_evidence_as_null():
    controller = RestartedMartingaleAlarmController(epsilon=0.5)

    result = controller.update(0.0)

    assert result["e_value"] is None
    assert result["e_value_is_infinite"] is True
    assert result["restarted_martingale"] is None
    assert result["restarted_martingale_is_infinite"] is True


def test_restarted_martingale_controller_handles_finite_log_overflow():
    controller = RestartedMartingaleAlarmController(epsilon=0.01)

    result = controller.update(float.fromhex("0x0.0000000000001p-1022"))

    assert result["log_e_value"] is not None
    assert result["e_value"] is None
    assert result["e_value_is_infinite"] is True


def test_static_conformal_real_pyod_nonconform_training_reaches_ready(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("RADAR_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv("SERVICE_ID", "static-conformal-test")
    clear_radar_runtime_settings_cache()
    config = _static_config(
        monkeypatch,
        martingale_config=StaticMartingaleConfig(epsilon=0.5),
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
        epsilon=0.5, alarm_count=2, tested_count=7
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


@pytest.mark.parametrize(
    ("missing_key", "expected_message"),
    [
        ("feature_keys", "feature_keys"),
        ("conformal_detector", "conformal_detector"),
        ("alarm_controller", "alarm_controller"),
    ],
)
def test_static_conformal_rejects_incomplete_ready_checkpoint(
    monkeypatch,
    tmp_path,
    missing_key,
    expected_message,
):
    config = _static_config(monkeypatch)
    checkpoint = {
        "strategy": "static_baseline",
        "static_state": "ready",
        "training_buffer": [],
        "calibration_buffer": [],
        "feature_keys": ["L1", "L2"],
        "conformal_detector": FakeConformalDetector(),
        "alarm_controller": RestartedMartingaleAlarmController(epsilon=0.5),
        "processed_count": 42,
        "anomaly_count": 3,
        "schema_signature": (
            StaticConformalDetectionService._build_schema_signature_from_config(config)
        ),
    }
    if missing_key == "feature_keys":
        checkpoint[missing_key] = []
    else:
        checkpoint[missing_key] = None
    checkpoint_path = tmp_path / f"missing-{missing_key}.pkl"
    checkpoint_path.write_bytes(pickle.dumps(checkpoint))

    with pytest.raises(ValueError, match=expected_message):
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
