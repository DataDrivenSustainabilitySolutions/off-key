"""Unit tests for static conformal RADAR detector lifecycle."""

import concurrent.futures
import pickle

from off_key_core.schemas.radar import FdrConfig, StaticBaselineConfig
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig
from off_key_mqtt_radar.config.runtime import clear_radar_runtime_settings_cache
from off_key_mqtt_radar.detector import (
    NaivePValueCutoffController,
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
    fdr_config: FdrConfig | None = None,
    model_params: dict | None = None,
    model_type: str = "pyod_iforest",
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
            training_window_size=20,
            calibration_fraction=0.25,
            fdr_config=fdr_config or FdrConfig(alpha=0.05, wealth=0.025, lambda_=0.5),
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


def test_static_conformal_naive_cutoff_flags_p_values_at_or_below_cutoff(
    monkeypatch,
):
    config = _static_config(
        monkeypatch,
        fdr_config=FdrConfig(method="naive", cutoff=0.05),
    )
    service = StaticConformalDetectionService(config)
    service.conformal_detector = FakeConformalDetector(p_value=0.05)
    service.fdr_controller = service._create_fdr_controller()
    service.feature_keys = ["L1", "L2"]
    service.state = StaticConformalState.READY

    result = service.process_data_point({"L1": 1.0, "L2": 2.0})

    assert result.is_anomaly is True
    assert result.context["static_conformal"]["fdr_method"] == "naive"
    assert result.context["static_conformal"]["fdr_threshold"] == 0.05
    assert result.context["static_conformal"]["tested_count"] == 1


def test_static_conformal_naive_cutoff_ignores_p_values_above_cutoff(monkeypatch):
    config = _static_config(
        monkeypatch,
        fdr_config=FdrConfig(method="naive", cutoff=0.05),
    )
    service = StaticConformalDetectionService(config)
    service.conformal_detector = FakeConformalDetector(p_value=0.051)
    service.fdr_controller = service._create_fdr_controller()
    service.feature_keys = ["L1", "L2"]
    service.state = StaticConformalState.READY

    result = service.process_data_point({"L1": 1.0, "L2": 2.0})

    assert result.is_anomaly is False
    assert result.severity == "low"
    assert result.context["static_conformal"]["fdr_method"] == "naive"
    assert result.context["static_conformal"]["tested_count"] == 1


def test_naive_p_value_cutoff_controller_tracks_test_count():
    controller = NaivePValueCutoffController(cutoff=0.05)

    assert controller.test_one(0.05) is True
    assert controller.test_one(0.0501) is False
    assert controller.num_test == 2


def test_real_saffron_controller_matches_static_detector_contract(monkeypatch):
    config = _static_config(monkeypatch)
    service = StaticConformalDetectionService(config)

    try:
        controller = service._create_fdr_controller()

        decision = controller.test_one(0.001)

        assert isinstance(decision, bool)
        assert int(getattr(controller, "num_test", 0)) == 1
    finally:
        service.shutdown()


def test_static_conformal_real_pyod_nonconform_training_reaches_ready(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("RADAR_CHECKPOINT_DIR", str(tmp_path))
    monkeypatch.setenv("SERVICE_ID", "static-conformal-test")
    clear_radar_runtime_settings_cache()
    config = _static_config(
        monkeypatch,
        fdr_config=FdrConfig(method="naive", cutoff=0.05),
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

        assert result.context["static_conformal"]["phase"] == "training_started"
        assert service.state == StaticConformalState.TRAINING

        service._complete_training_if_ready()

        assert service.state == StaticConformalState.READY, service.training_error

        result = service.process_data_point({"L1": 100.0, "L2": 20.0})
        static_context = result.context["static_conformal"]
        assert static_context["phase"] == "ready"
        assert static_context["fdr_method"] == "naive"
        assert 0.0 <= static_context["p_value"] <= 1.0
        assert 0.0 <= result.anomaly_score <= 1.0
    finally:
        service.shutdown()
        clear_radar_runtime_settings_cache()


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
