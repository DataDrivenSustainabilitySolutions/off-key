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
from off_key_core.models.adaptive import PRETRAINED_FORECASTERS, aberrant_model
from off_key_core.schemas.radar import AdaptiveStreamConfig
from off_key_mqtt_radar.adaptive_detector import (
    AdaptiveStreamDetectionService,
    AdaptiveStreamState,
)
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig
from off_key_mqtt_radar.execution_errors import (
    FatalExecutionError,
    ObservationRejected,
)
from pydantic import ValidationError

from tests.support import forecast_service
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
    "aberrant_seasonal_residual_detector": {"season_length": 4},
    "aberrant_holt_winters_forecaster": {"season_length": 4, "lead": 2},
    "aberrant_seasonal_naive_forecaster": {"season_length": 4},
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
    if model_type in PRETRAINED_FORECASTERS:
        warmup = validated_params["minimum_context"] + validated_params["lead"] - 1
    else:
        warmup = (
            get_model_spec(ADAPTIVE_MODELS_BY_TYPE[model_type]["catalog_id"])
            .capabilities(
                aberrant_model(ADAPTIVE_MODELS_BY_TYPE[model_type], validated_params)[
                    "params"
                ]
            )
            .warmup.minimum
        )
    minimum = max(2, warmup or 0)
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
    assert len(ADAPTIVE_MODELS_BY_TYPE) == 30
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
    tmp_path,
) -> None:
    forecast_service.start(monkeypatch, tmp_path)
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
        "aberrant_seasonal_residual_detector",
        "aberrant_holt_winters_forecaster",
        "aberrant_seasonal_naive_forecaster",
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


def test_seasonal_warmup_of_two_seasons_must_fit_the_training_window():
    with pytest.raises(ValueError, match="at least 48 updates"):
        AdaptiveStreamDetectionService(
            _config(
                AdaptiveStreamConfig(
                    model_type="aberrant_seasonal_residual_detector",
                    model_params={"season_length": 24},
                    training_window_size=47,
                ),
                _features(1),
            )
        )


def test_seasonal_residual_scores_a_break_in_the_cycle_above_the_cycle():
    pattern = [0.0, 10.0, 0.0, -10.0]
    config = _runtime_config(
        "aberrant_seasonal_residual_detector", training=8, calibration=4
    )
    detector = AdaptiveStreamDetectionService(config)
    scores = [
        detector.process_data_point({"x0": 100.0 + pattern[index % 4]}).anomaly_score
        for index in range(40)
    ]
    # The reading arrives where the cycle expects its trough.
    spike = detector.process_data_point({"x0": 110.0})

    assert detector.state is AdaptiveStreamState.OPERATIONAL
    assert max(scores[12:]) < 0.5
    assert spike.anomaly_score > 10 * max(scores[12:], default=0.0) + 1


def test_forecaster_warmup_of_two_seasons_and_its_lead_must_fit_training():
    with pytest.raises(ValueError, match="at least 53 updates"):
        AdaptiveStreamDetectionService(
            _config(
                AdaptiveStreamConfig(
                    model_type="aberrant_holt_winters_forecaster",
                    model_params={"season_length": 24, "lead": 6},
                    training_window_size=52,
                ),
                _features(1),
            )
        )


@pytest.mark.parametrize(
    ("model_type", "lead"),
    [
        ("aberrant_holt_winters_forecaster", 1),
        ("aberrant_holt_winters_forecaster", 3),
        ("aberrant_seasonal_naive_forecaster", 1),
        ("aberrant_seasonal_naive_forecaster", 2),
    ],
)
def test_forecaster_scores_a_break_in_the_cycle_above_the_cycle(model_type, lead):
    pattern = [0.0, 10.0, 0.0, -10.0]
    adaptive = AdaptiveStreamConfig(
        model_type=model_type,
        model_params={"season_length": 4, "lead": lead},
        training_window_size=12,
        calibration_window_size=4,
    )
    detector = AdaptiveStreamDetectionService(_config(adaptive, _features(1)))
    scores = [
        detector.process_data_point({"x0": 100.0 + pattern[index % 4]}).anomaly_score
        for index in range(40)
    ]
    # The reading arrives where the cycle expects its trough.
    spike = detector.process_data_point({"x0": 110.0})

    assert detector.state is AdaptiveStreamState.OPERATIONAL
    assert max(scores[16:]) < 0.5
    assert spike.anomaly_score > 10 * max(scores[16:], default=0.0) + 1


def test_holt_winters_forecaster_at_lead_one_is_the_seasonal_residual_detector():
    cycle = [0.0, 10.0, 0.0, -10.0]
    values = [100.0 + cycle[index % 4] + index for index in range(40)]

    def scores(model_type: str) -> list[float]:
        adaptive = AdaptiveStreamConfig(
            model_type=model_type,
            model_params={"season_length": 4},
            training_window_size=8,
            calibration_window_size=4,
        )
        detector = AdaptiveStreamDetectionService(_config(adaptive, _features(1)))
        return [
            detector.process_data_point({"x0": value}).anomaly_score for value in values
        ]

    assert scores("aberrant_holt_winters_forecaster") == pytest.approx(
        scores("aberrant_seasonal_residual_detector")
    )


def _timestral(lead: int = 1, training: int = 20, **params) -> AnomalyDetectionConfig:
    adaptive = AdaptiveStreamConfig(
        model_type="forecast.timestral",
        model_params={"context_length": 32, "minimum_context": 16, "lead": lead}
        | params,
        training_window_size=training,
        calibration_window_size=4,
    )
    return _config(adaptive, _features(1))


@pytest.mark.parametrize("lead", [1, 3])
def test_timestral_step_scores_a_break_in_the_cycle_through_the_service(
    monkeypatch, tmp_path, lead
):
    service = forecast_service.start(monkeypatch, tmp_path, season_length=4)
    pattern = [0.0, 10.0, 0.0, -10.0]
    detector = AdaptiveStreamDetectionService(_timestral(lead))
    scores = [
        detector.process_data_point({"x0": 100.0 + pattern[index % 4]}).anomaly_score
        for index in range(40)
    ]
    spike = detector.process_data_point({"x0": 110.0})

    assert detector.state is AdaptiveStreamState.OPERATIONAL
    assert max(scores[24:]) < 0.5
    assert spike.anomaly_score > 10 * max(scores[24:], default=0.0) + 1
    # The first value asks for the model, then one forecast per value from the
    # sixteenth on; the weights stay in the service.
    assert service["calls"] == [
        ("POST", "http://forecast/v1/downloads"),
        *[("POST", "http://forecast/v1/forecast")] * 26,
    ]
    assert detector.model_capabilities["warmup"] == {
        "minimum": 16 + lead - 1,
        "unit": "events",
    }


def test_timestral_warmup_must_fit_the_training_window(monkeypatch, tmp_path):
    forecast_service.start(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="at least 18 updates"):
        AdaptiveStreamDetectionService(_timestral(lead=3, training=17))


def test_timestral_checkpoint_restores_without_its_connection(monkeypatch, tmp_path):
    forecast_service.start(monkeypatch, tmp_path, season_length=4)
    config = _timestral(lead=2)
    detector = AdaptiveStreamDetectionService(config)
    for index in range(30):
        detector.process_data_point({"x0": 100.0 + index % 4})

    checkpoint = pickle.loads(pickle.dumps(detector.export_checkpoint()))
    restored = AdaptiveStreamDetectionService.from_checkpoint_data(checkpoint, config)
    expected = detector.process_data_point({"x0": 140.0})
    result = restored.process_data_point({"x0": 140.0})

    assert restored.state is AdaptiveStreamState.OPERATIONAL
    assert result.anomaly_score == expected.anomaly_score > 1
    assert restored.detector_fingerprint == detector.detector_fingerprint


def test_timestral_outage_rejects_observations_and_the_run_recovers(
    monkeypatch, tmp_path
):
    service = forecast_service.start(monkeypatch, tmp_path, season_length=4)
    detector = AdaptiveStreamDetectionService(_timestral())
    for index in range(30):
        detector.process_data_point({"x0": 100.0 + index % 4})

    # The service goes away: the value before the outage is still compared
    # with its forecast, the next has none.
    monkeypatch.setitem(service, "down", True)
    for pipeline in detector.pipelines:
        pipeline.model.model._client = None
    assert math.isfinite(detector.process_data_point({"x0": 102.0}).anomaly_score)
    for _ in range(3):
        with pytest.raises(ObservationRejected, match="No forecast to compare with"):
            detector.process_data_point({"x0": 103.0})
    assert detector.state is AdaptiveStreamState.OPERATIONAL

    monkeypatch.setitem(service, "down", False)
    result = detector.process_data_point({"x0": 140.0})
    assert result.anomaly_score > 1 and result.is_anomaly


def test_timestral_run_ends_when_the_service_does_not_offer_the_checkpoint(
    monkeypatch, tmp_path
):
    forecast_service.start(
        monkeypatch, tmp_path, checkpoints=("mistralai/Timestral-28M",)
    )
    detector = AdaptiveStreamDetectionService(_timestral())

    with pytest.raises(FatalExecutionError, match="does not offer") as error:
        detector.process_data_point({"x0": 100.0})
    assert "mistralai/Timestral-5M" in str(error.value)
    assert detector.state is AdaptiveStreamState.FAILED


def test_timestral_settings_are_checked_before_a_run_starts(monkeypatch, tmp_path):
    forecast_service.start(monkeypatch, tmp_path)
    with pytest.raises(ValidationError, match="minimum_context"):
        _timestral(context_length=16, minimum_context=32)
    with pytest.raises(ValidationError):
        _timestral(checkpoint="mistralai/Timestral-1B")
    with pytest.raises(ValidationError):
        _timestral(horizon=4)


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
