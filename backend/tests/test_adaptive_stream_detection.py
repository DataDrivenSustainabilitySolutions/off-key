"""Real Aberrant 0.5.0 adapter and adaptive lifecycle coverage."""

from __future__ import annotations

import importlib
import math
from pathlib import Path
from typing import Any

import pytest
from off_key_core.models import (
    ADAPTIVE_MODEL_DEFINITIONS,
    minimum_model_warmup,
    validate_adaptive_model_params,
)
from off_key_core.schemas.radar import AdaptiveStreamConfig
from off_key_mqtt_radar.adaptive_detector import (
    AdaptiveStreamDetectionService,
    AdaptiveStreamState,
)
from off_key_mqtt_radar.checkpoint_manager import CheckpointManager
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig
from pydantic import ValidationError

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
    return {}


def _feature_count(model_type: str) -> int:
    definition = next(
        item for item in ADAPTIVE_MODEL_DEFINITIONS if item.model_type == model_type
    )
    return 1 if definition.feature_count == "one" else 2


def _runtime_config(
    model_type: str,
    *,
    training: int | None = None,
    calibration: int = 1,
    preprocessing_steps: list[dict[str, Any]] | None = None,
) -> AnomalyDetectionConfig:
    params = _params(model_type)
    validated_params = validate_adaptive_model_params(model_type, params)
    minimum = max(2, minimum_model_warmup(model_type, validated_params))
    adaptive = AdaptiveStreamConfig(
        model_type=model_type,
        model_params=params,
        training_window_size=training or minimum,
        calibration_window_size=calibration,
        preprocessing_steps=preprocessing_steps or [],
    )
    return AnomalyDetectionConfig(
        strategy="adaptive_stream",
        model_type=model_type,
        model_params=adaptive.model_params,
        adaptive_stream_config=adaptive,
        subscription_topics=["device/evCharger/c1/x"],
        checkpoint_interval=1_000_000,
    )


def _point(index: int, count: int) -> dict[str, float]:
    return {f"x{feature}": float(index + feature / 10) for feature in range(count)}


def test_catalog_is_the_24_released_numeric_detectors() -> None:
    assert len(ADAPTIVE_MODEL_DEFINITIONS) == 24
    assert len({item.model_type for item in ADAPTIVE_MODEL_DEFINITIONS}) == 24
    for definition in ADAPTIVE_MODEL_DEFINITIONS:
        module_name, class_name = definition.import_path.rsplit(".", 1)
        assert getattr(importlib.import_module(module_name), class_name)


@pytest.mark.parametrize(
    "definition",
    ADAPTIVE_MODEL_DEFINITIONS,
    ids=lambda item: item.model_type,
)
def test_every_released_detector_runs_warmup_calibration_and_operational(
    definition: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _runtime_config(definition.model_type)
    detector = AdaptiveStreamDetectionService(config)
    monkeypatch.setattr(detector, "_checkpoint_model", lambda: None)
    count = _feature_count(definition.model_type)
    total = config.adaptive_stream_config.training_window_size + 2  # type: ignore[union-attr]
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
    monkeypatch.setattr(detector, "_checkpoint_model", lambda: None)
    results = [detector.process_data_point(_point(index, 2)) for index in range(4)]
    assert results[-1].context["adaptive_stream"]["phase"] == "operational"
    assert math.isfinite(results[-1].anomaly_score)


class _RecordingPipeline:
    def __init__(self, scores: list[float]):
        self.scores = iter(scores)
        self.learned: list[float] = []

    def score_one(self, point: dict[str, float]) -> float:
        assert point["x"] not in self.learned
        return next(self.scores)

    def learn_one(self, point: dict[str, float]) -> None:
        self.learned.append(point["x"])


def test_score_then_learn_quantile_max_and_strict_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _runtime_config(
        "aberrant_online_isolation_forest", training=2, calibration=3
    )
    detector = AdaptiveStreamDetectionService(config)
    recorder = _RecordingPipeline([1.0, 3.0, 2.0, 3.0])
    detector.pipeline = recorder
    detector.feature_keys = ["x"]
    monkeypatch.setattr(detector, "_checkpoint_model", lambda: None)

    results = [detector.process_data_point({"x": float(index)}) for index in range(6)]

    assert detector.threshold == 3.0
    assert detector.state is AdaptiveStreamState.OPERATIONAL
    assert results[-1].anomaly_score == 3.0
    assert results[-1].is_anomaly is False
    assert recorder.learned == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]


def test_knn_faiss_checkpoint_round_trip_continues_operationally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = CheckpointManager(str(tmp_path), "adaptive-knn")
    monkeypatch.setattr(
        "off_key_mqtt_radar.adaptive_detector.CheckpointManager", lambda: manager
    )
    config = _runtime_config("aberrant_knn", training=2)
    detector = AdaptiveStreamDetectionService(config)
    for index in range(3):
        detector.process_data_point(_point(index, 2))

    [checkpoint_path] = manager.candidate_paths()
    restored = AdaptiveStreamDetectionService.from_checkpoint(checkpoint_path, config)
    result = restored.process_data_point(_point(4, 2))

    assert restored.state is AdaptiveStreamState.OPERATIONAL
    assert result.context["adaptive_stream"]["phase"] == "operational"
    assert math.isfinite(result.anomaly_score)


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
