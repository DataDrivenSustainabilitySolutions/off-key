"""Real Aberrant catalog adapter and adaptive lifecycle coverage."""

from __future__ import annotations

import math
import pickle
from typing import Any

import pytest
from aberrant.catalog import get_model_spec
from off_key_core.models import (
    ADAPTIVE_MODELS_BY_TYPE,
    validate_adaptive_model_params,
)
from off_key_core.schemas.radar import AdaptiveStreamConfig
from off_key_mqtt_radar.adaptive_detector import (
    AdaptiveStreamDetectionService,
    AdaptiveStreamState,
)
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig
from off_key_mqtt_radar.execution_errors import ObservationRejected
from pydantic import ValidationError

from tests.support.form_pipeline import form_radar_config

FAST_PARAMS: dict[str, dict[str, Any]] = {
    "aberrant_asd_isolation_forest": {"n_estimators": 2, "max_samples": 2, "seed": 1},
    "aberrant_half_space_trees": {
        "n_trees": 2,
        "height": 2,
        "window_size": 2,
        "seed": 1,
    },
    "aberrant_mondrian_forest": {"n_estimators": 2, "subspace_size": 2, "seed": 1},
    "aberrant_online_isolation_forest": {
        "num_trees": 2,
        "max_leaf_samples": 2,
        "window_size": 8,
        "n_jobs": 1,
    },
    "aberrant_random_cut_forest": {"n_trees": 2, "sample_size": 2, "seed": 1},
    "aberrant_stream_random_histogram_forest": {
        "n_estimators": 2,
        "max_bins": 2,
        "window_size": 2,
        "seed": 1,
    },
    "aberrant_x_stream": {
        "k": 2,
        "n_chains": 2,
        "depth": 2,
        "cms_width": 8,
        "cms_num_hashes": 2,
        "window_size": 2,
        "init_sample_size": 2,
        "seed": 1,
    },
    "aberrant_knn": {"k": 1, "window_size": 8, "warm_up": 1},
    "aberrant_local_outlier_factor": {"k": 1, "window_size": 8},
}


def _params(model_type: str) -> dict[str, Any]:
    if model_type in FAST_PARAMS:
        return FAST_PARAMS[model_type]
    if model_type == "aberrant_moving_mahalanobis_distance":
        return {"window_size": 3}
    if model_type.startswith("aberrant_moving_"):
        params: dict[str, Any] = {"window_size": 2}
        if model_type == "aberrant_moving_quantile":
            params["quantile"] = 0.5
        return params
    if "rolling_matrix_profile" in model_type:
        return {"subsequence_length": 4, "window_size": 16}
    return {}


def _feature_count(model_type: str) -> int:
    limits = ADAPTIVE_MODELS_BY_TYPE[model_type]["default_capabilities"][
        "feature_count"
    ]
    return 1 if limits["maximum"] == 1 else 2


def _runtime_config(
    model_type: str,
    *,
    training: int | None = None,
    calibration: int = 1,
    preprocessing_steps: list[dict[str, Any]] | None = None,
    features: list[str] | None = None,
) -> AnomalyDetectionConfig:
    params = _params(model_type)
    validated_params = validate_adaptive_model_params(model_type, params)
    minimum = max(
        2,
        get_model_spec(ADAPTIVE_MODELS_BY_TYPE[model_type]["catalog_id"])
        .capabilities(validated_params)
        .warmup.minimum
        or 0,
    )
    if preprocessing_steps is None and model_type == "aberrant_half_space_trees":
        preprocessing_steps = [{"type": "min_max_scaler"}]
    adaptive = AdaptiveStreamConfig(
        model_type=model_type,
        model_params=params,
        training_window_size=training or minimum,
        calibration_window_size=calibration,
        preprocessing_steps=preprocessing_steps or [],
    )
    return _config(adaptive, features or _features(_feature_count(model_type)))


def _features(count: int) -> list[str]:
    return [f"x{feature}" for feature in range(count)]


def _config(
    adaptive: AdaptiveStreamConfig, features: list[str]
) -> AnomalyDetectionConfig:
    return form_radar_config(
        adaptive,
        [f"telemetry/c1/{feature}" for feature in features],
        checkpoint_interval=1_000_000,
    )


def _point(index: int, count: int) -> dict[str, float]:
    # Positive readings suit every model, including geometric averages.
    return {f"x{feature}": float(index + 1 + feature / 10) for feature in range(count)}


def _record(detector, scores: list[float]) -> list[float]:
    """Script the graph's scores and check every score precedes its learning."""
    scripted, learned = iter(scores), []
    learn = detector.pipeline.learn_one

    def score_one(point: dict[str, float]) -> float:
        assert point["input_1"] not in learned
        return next(scripted)

    def learn_one(point: dict[str, float]) -> None:
        learned.append(point["input_1"])
        learn(point)

    detector.pipeline.score_one = score_one
    detector.pipeline.learn_one = learn_one
    return learned


def test_catalog_contains_only_supported_numeric_detectors() -> None:
    assert len(ADAPTIVE_MODELS_BY_TYPE) == 26
    for definition in ADAPTIVE_MODELS_BY_TYPE.values():
        spec = get_model_spec(definition["catalog_id"])
        assert spec.load()
        assert definition["default_capabilities"]["event_kind"] in {
            "tabular",
            "univariate",
            "bivariate",
        }


@pytest.mark.parametrize("model_type", ADAPTIVE_MODELS_BY_TYPE)
def test_every_released_detector_runs_warmup_calibration_and_operational(
    model_type: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _runtime_config(model_type)
    detector = AdaptiveStreamDetectionService(config)
    count = _feature_count(model_type)
    total = config.monitoring.training_window_size + 2
    results = [
        detector.process_data_point(_point(index, count)) for index in range(total)
    ]

    assert results[0].context["adaptive_stream"]["phase"] == "warmup"
    assert results[-2].context["adaptive_stream"]["phase"] == "calibration"
    assert results[-1].context["adaptive_stream"]["phase"] == "operational"
    assert math.isfinite(results[-1].anomaly_score)


@pytest.mark.parametrize(
    "step",
    [
        {"type": "standard_scaler"},
        {"type": "min_max_scaler"},
        {"type": "incremental_pca", "n_components": 1, "n0": 2},
        {"type": "random_projection", "n_components": 1, "seed": 7},
    ],
    ids=["standard", "min-max", "incremental-pca", "random-projection"],
)
def test_all_released_transforms_feed_real_detector(
    step: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _runtime_config(
        "aberrant_online_isolation_forest",
        training=2,
        preprocessing_steps=[step],
    )
    detector = AdaptiveStreamDetectionService(config)
    # PCA initialises on its own points before the model learns any.
    results = [detector.process_data_point(_point(index, 2)) for index in range(6)]
    assert results[-1].context["adaptive_stream"]["phase"] == "operational"
    assert math.isfinite(results[-1].anomaly_score)


def test_score_then_learn_quantile_max_and_strict_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _runtime_config(
        "aberrant_moving_average", training=2, calibration=3, features=["x"]
    )
    detector = AdaptiveStreamDetectionService(config)
    learned = _record(detector, [1.0, 3.0, 2.0, 3.0])

    results = [detector.process_data_point({"x": float(index)}) for index in range(6)]

    assert detector.threshold == 3.0
    assert detector.state is AdaptiveStreamState.OPERATIONAL
    assert results[-1].anomaly_score == 3.0
    assert results[-1].is_anomaly is False
    assert learned == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]


@pytest.mark.parametrize(
    "model_type",
    [
        "aberrant_knn",
        "aberrant_half_space_trees",
        "aberrant_rolling_matrix_profile",
        "aberrant_multivariate_rolling_matrix_profile",
    ],
)
def test_native_pipeline_checkpoint_preserves_future_scores(model_type: str) -> None:
    config = _runtime_config(model_type)
    detector = AdaptiveStreamDetectionService(config)
    feature_count = _feature_count(model_type)
    total = config.monitoring.training_window_size + 1
    for index in range(total):
        detector.process_data_point(_point(index, feature_count))

    checkpoint = pickle.loads(pickle.dumps(detector.export_checkpoint()))
    restored = AdaptiveStreamDetectionService.from_checkpoint_data(checkpoint, config)
    next_point = _point(total + 1, feature_count)
    expected = detector.process_data_point(next_point)
    result = restored.process_data_point(next_point)

    assert restored.state is AdaptiveStreamState.OPERATIONAL
    assert result.context["adaptive_stream"]["phase"] == "operational"
    assert math.isfinite(result.anomaly_score)
    assert result.anomaly_score == expected.anomaly_score
    assert result.is_anomaly == expected.is_anomaly
    assert result.severity == expected.severity
    assert restored.detector_fingerprint == detector.detector_fingerprint


def test_config_rejects_invalid_preprocessing_and_knn_warmup() -> None:
    with pytest.raises(ValidationError, match="scaler must precede"):
        AdaptiveStreamConfig(
            preprocessing_steps=[
                {"type": "random_projection", "n_components": 1},
                {"type": "standard_scaler"},
            ]
        )
    with pytest.raises(ValidationError, match="k <= warm_up <= window_size"):
        AdaptiveStreamConfig(
            model_type="aberrant_knn",
            model_params={"k": 5, "warm_up": 3, "window_size": 10},
        )


def test_runtime_validates_parameter_dependent_warmup_before_learning():
    with pytest.raises(ValueError, match="warm-up"):
        AdaptiveStreamDetectionService(
            _config(
                AdaptiveStreamConfig(
                    model_type="aberrant_random_cut_forest",
                    model_params={"n_trees": 2, "sample_size": 20},
                    training_window_size=2,
                ),
                _features(2),
            )
        )


def test_pca_initialization_cannot_be_shortened_by_model_warmup():
    with pytest.raises(ValidationError, match="warm-up"):
        AdaptiveStreamConfig(
            training_window_size=5,
            preprocessing_steps=[
                {"type": "incremental_pca", "n_components": 1, "n0": 20}
            ],
        )


def test_runtime_executes_constructor_validation_at_startup():
    from aberrant.base import ConfigurationError

    adaptive = AdaptiveStreamConfig(
        model_type="aberrant_rolling_matrix_profile",
        model_params={"subsequence_length": 8, "window_size": 8},
    )
    with pytest.raises(ConfigurationError, match="window_size"):
        AdaptiveStreamDetectionService(_config(adaptive, _features(1)))


def test_half_space_trees_bounds_new_extremes_before_scoring(monkeypatch):
    detector = AdaptiveStreamDetectionService(
        _runtime_config("aberrant_half_space_trees", features=["x"])
    )
    detector.process_data_point({"x": 0.0})
    detector.process_data_point({"x": 1.0})
    for value, scaled in ((100.0, 1.0), (-100.0, 0.0)):
        result = detector.process_data_point({"x": value})
        assert math.isfinite(result.anomaly_score)
        assert result.processed_features == {"input_1": scaled}


def test_half_space_trees_rejects_unscaled_out_of_domain_data():
    detector = AdaptiveStreamDetectionService(
        _runtime_config(
            "aberrant_half_space_trees", preprocessing_steps=[], features=["x"]
        )
    )
    with pytest.raises(ObservationRejected, match=r"must be in \[0, 1\]"):
        detector.process_data_point({"x": 2.0})
    assert detector.processed_count == 0


def test_severity_uses_excess_over_signed_threshold(monkeypatch):
    detector = AdaptiveStreamDetectionService(
        _runtime_config(
            "aberrant_moving_average", training=2, calibration=2, features=["x"]
        )
    )
    _record(detector, [-4.0, -2.0, -1.9, 0.0])
    results = [detector.process_data_point({"x": float(i)}) for i in range(6)]
    assert detector.threshold == -2.0
    assert results[-2].is_anomaly is True
    assert results[-2].severity == "medium"
    assert results[-1].severity == "high"


@pytest.mark.parametrize(
    "field,value",
    [
        ("aberrant_version", "0.5.0"),
        ("detector_fingerprint", "different-configuration"),
        ("detector_config", {}),
    ],
)
def test_checkpoint_rejects_incompatible_runtime_or_configuration(field, value):
    config = _runtime_config("aberrant_knn", training=2)
    detector = AdaptiveStreamDetectionService(config)
    for index in range(3):
        detector.process_data_point(_point(index, 2))
    checkpoint = pickle.loads(pickle.dumps(detector.export_checkpoint()))
    checkpoint[field] = value
    with pytest.raises(ValueError, match="incompatible"):
        AdaptiveStreamDetectionService.from_checkpoint_data(checkpoint, config)
