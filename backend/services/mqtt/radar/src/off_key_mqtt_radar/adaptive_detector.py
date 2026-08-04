"""Aberrant-backed score-then-learn adaptive stream detector."""

import hashlib
import importlib
import json
import logging
import math
import os
import time
from collections import deque
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import numpy as np
import psutil
from aberrant.base.pipeline import Pipeline
from aberrant.model.distance import KNN
from aberrant.transform import (
    IncrementalPCA,
    MinMaxScaler,
    RandomProjection,
    StandardScaler,
)
from aberrant.utils.similar.faiss_engine import FaissSimilaritySearchEngine
from off_key_core.models import ABERRANT_VERSION, ADAPTIVE_MODELS_BY_TYPE
from off_key_core.schemas.radar import (
    AdaptiveStreamConfig,
    IncrementalPCAConfig,
    MinMaxScalerConfig,
    RandomProjectionConfig,
    StandardScalerConfig,
)

from .checkpoint_manager import CheckpointManager
from .config.config import AnomalyDetectionConfig
from .models import AnomalyResult


class AdaptiveStreamState(Enum):
    WARMUP = "warmup"
    CALIBRATING = "calibrating"
    OPERATIONAL = "operational"
    FAILED = "failed"


class AdaptiveStreamDetectionService:
    """Online detector with bounded warm-up and frozen score calibration."""

    def __init__(
        self,
        config: AnomalyDetectionConfig,
        checkpoint: dict[str, Any] | None = None,
    ) -> None:
        self.config = config
        adaptive_config = config.adaptive_stream_config
        if adaptive_config is None:
            raise ValueError("adaptive_stream_config is required")
        self.adaptive_config: AdaptiveStreamConfig = adaptive_config
        self.logger = logging.getLogger(__name__)
        self.schema_signature = self._build_schema_signature(config)
        self.start_time = time.time()
        self.processing_times: deque[float] = deque(maxlen=1000)
        self.training_error: str | None = None
        if checkpoint is None:
            self._initialize_fresh()
        else:
            self._restore(checkpoint)

    def _initialize_fresh(self) -> None:
        self.state = AdaptiveStreamState.WARMUP
        self.feature_keys: list[str] = []
        self.pipeline: Any | None = None
        self.calibration_scores: list[float] = []
        self.threshold: float | None = None
        self.processed_count = 0
        self.warmup_count = 0
        self.calibration_count = 0
        self.operational_count = 0
        self.anomaly_count = 0
        self.schema_mismatch_count = 0
        self.last_checkpoint = 0

    def _restore(self, checkpoint: dict[str, Any]) -> None:
        self.state = AdaptiveStreamState(checkpoint["adaptive_state"])
        self.feature_keys = list(checkpoint["feature_keys"])
        self.pipeline = checkpoint["pipeline"]
        self.calibration_scores = list(checkpoint.get("calibration_scores", []))
        self.threshold = checkpoint.get("threshold")
        self.processed_count = int(checkpoint.get("processed_count", 0))
        self.warmup_count = int(checkpoint.get("warmup_count", 0))
        self.calibration_count = int(checkpoint.get("calibration_count", 0))
        self.operational_count = int(checkpoint.get("operational_count", 0))
        self.anomaly_count = int(checkpoint.get("anomaly_count", 0))
        self.schema_mismatch_count = int(checkpoint.get("schema_mismatch_count", 0))
        self.last_checkpoint = self.processed_count
        self.training_error = checkpoint.get("training_error")
        if self.pipeline is None or not self.feature_keys:
            raise ValueError("Adaptive checkpoint is missing pipeline state")
        if self.state == AdaptiveStreamState.OPERATIONAL and self.threshold is None:
            raise ValueError("Operational adaptive checkpoint has no threshold")

    @classmethod
    def from_checkpoint(
        cls, checkpoint_path: str, config: AnomalyDetectionConfig
    ) -> "AdaptiveStreamDetectionService":
        checkpoint = CheckpointManager().load(checkpoint_path)
        if checkpoint.get("strategy") != "adaptive_stream":
            raise ValueError("Checkpoint strategy does not match adaptive_stream")
        if checkpoint.get("aberrant_version") != ABERRANT_VERSION:
            raise ValueError("Checkpoint aberrant version is incompatible")
        if checkpoint.get("schema_signature") != cls._build_schema_signature(config):
            raise ValueError("Adaptive checkpoint configuration is incompatible")
        return cls(config, checkpoint=checkpoint)

    @staticmethod
    def _build_schema_signature(config: AnomalyDetectionConfig) -> str:
        adaptive_config = config.adaptive_stream_config
        payload = {
            "strategy": "adaptive_stream",
            "adaptive_stream_config": (
                adaptive_config.model_dump(mode="json", exclude_none=True)
                if adaptive_config
                else None
            ),
            "subscription_topics": sorted(config.subscription_topics),
            "sensor_key_strategy": config.sensor_key_strategy,
            "aberrant_version": ABERRANT_VERSION,
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode()).hexdigest()

    def _freeze_schema_and_build_pipeline(self, data: dict[str, float]) -> None:
        self.feature_keys = sorted(data)
        self.adaptive_config.validate_feature_schema(self.feature_keys)

        component: Any | None = None
        current_keys = list(self.feature_keys)
        for step in self.adaptive_config.preprocessing_steps:
            transformer = self._build_transformer(step, current_keys)
            component = (
                transformer if component is None else Pipeline(component, transformer)
            )
            if isinstance(step, IncrementalPCAConfig | RandomProjectionConfig):
                current_keys = [
                    f"component_{index}" for index in range(step.n_components)
                ]
        model = self._build_model(self.adaptive_config.model_type, current_keys)
        self.pipeline = model if component is None else Pipeline(component, model)

    def _build_model(self, model_type: str, feature_keys: list[str]) -> Any:
        definition = ADAPTIVE_MODELS_BY_TYPE[model_type]
        params = dict(self.adaptive_config.model_params)
        if model_type == "aberrant_knn":
            engine = FaissSimilaritySearchEngine(
                window_size=int(params.pop("window_size")),
                warm_up=int(params.pop("warm_up")),
            )
            return KNN(similarity_engine=engine, **params)
        if model_type == "aberrant_online_isolation_forest":
            params["type"] = params.pop("tree_type")
        if model_type == "aberrant_moving_geometric_average":
            params["absoluteValues"] = params.pop("absolute_values")
        if definition.feature_count == "one":
            params["key"] = feature_keys[0] if len(feature_keys) == 1 else None
            params["abs_diff"] = True
        elif definition.feature_count == "two":
            params["keys"] = feature_keys if len(feature_keys) == 2 else None
            params["abs_diff"] = True
        elif model_type == "aberrant_moving_mahalanobis_distance":
            params["keys"] = feature_keys
        module_name, class_name = definition.import_path.rsplit(".", 1)
        model_class = getattr(importlib.import_module(module_name), class_name)
        return model_class(**params)

    @staticmethod
    def _build_transformer(step: Any, feature_keys: list[str]) -> Any:
        if isinstance(step, StandardScalerConfig):
            return StandardScaler(with_std=step.with_std)
        if isinstance(step, MinMaxScalerConfig):
            return MinMaxScaler(feature_range=step.feature_range)
        if isinstance(step, IncrementalPCAConfig):
            return IncrementalPCA(
                n_components=step.n_components,
                n0=step.n0,
                keys=feature_keys,
                tol=step.tol,
                forgetting_factor=step.forgetting_factor,
            )
        if isinstance(step, RandomProjectionConfig):
            return RandomProjection(
                n_components=step.n_components,
                keys=feature_keys,
                seed=step.seed,
            )
        raise TypeError(f"Unsupported adaptive preprocessing step: {step!r}")

    def process_data_point(
        self,
        data: dict[str, float],
        topic: str | None = None,
        charger_id: str | None = None,
    ) -> AnomalyResult:
        started = time.time()
        try:
            normalized = self._validate_data(data)
            if self.pipeline is None:
                self._freeze_schema_and_build_pipeline(normalized)
            elif sorted(normalized) != self.feature_keys:
                self.schema_mismatch_count += 1
                raise ValueError(
                    f"Adaptive feature schema changed; expected {self.feature_keys}"
                )

            result = self._process_current_state(normalized, topic, charger_id, started)
        except Exception as exc:
            self.state = AdaptiveStreamState.FAILED
            self.training_error = str(exc)
            raise

        if (
            self.processed_count
            and self.processed_count % self.config.checkpoint_interval == 0
        ):
            self._checkpoint_model()
        return result

    def _process_current_state(
        self,
        data: dict[str, float],
        topic: str | None,
        charger_id: str | None,
        started: float,
    ) -> AnomalyResult:
        if self.state == AdaptiveStreamState.WARMUP:
            return self._process_warmup(data, topic, charger_id, started)
        if self.state == AdaptiveStreamState.CALIBRATING:
            return self._process_calibration(data, topic, charger_id, started)
        if self.state == AdaptiveStreamState.OPERATIONAL:
            return self._process_operational(data, topic, charger_id, started)
        raise RuntimeError(self.training_error or "Adaptive detector failed")

    def _process_warmup(
        self,
        data: dict[str, float],
        topic: str | None,
        charger_id: str | None,
        started: float,
    ) -> AnomalyResult:
        self.pipeline.learn_one(data)
        self.warmup_count += 1
        self.processed_count += 1
        if self.warmup_count >= self.adaptive_config.training_window_size:
            self.state = AdaptiveStreamState.CALIBRATING
        return self._result(data, 0.0, False, "warmup", topic, charger_id, started)

    def _process_calibration(
        self,
        data: dict[str, float],
        topic: str | None,
        charger_id: str | None,
        started: float,
    ) -> AnomalyResult:
        score = self._score(data)
        self.pipeline.learn_one(data)
        self.calibration_scores.append(score)
        self.calibration_count += 1
        self.processed_count += 1
        if self.calibration_count >= self.adaptive_config.calibration_window_size:
            self.threshold = float(
                np.quantile(
                    np.asarray(self.calibration_scores, dtype=float),
                    self.adaptive_config.threshold_config.quantile,
                    method="higher",
                )
            )
            self.state = AdaptiveStreamState.OPERATIONAL
            self._checkpoint_model()
        return self._result(
            data, score, False, "calibration", topic, charger_id, started
        )

    def _process_operational(
        self,
        data: dict[str, float],
        topic: str | None,
        charger_id: str | None,
        started: float,
    ) -> AnomalyResult:
        if self.threshold is None:
            raise RuntimeError("Adaptive threshold is not initialized")
        score = self._score(data)
        is_anomaly = score > self.threshold
        self.pipeline.learn_one(data)
        self.operational_count += 1
        self.processed_count += 1
        if is_anomaly:
            self.anomaly_count += 1
        return self._result(
            data, score, is_anomaly, "operational", topic, charger_id, started
        )

    @staticmethod
    def _validate_data(data: dict[str, float]) -> dict[str, float]:
        if not data:
            raise ValueError("Adaptive detector requires at least one feature")
        normalized = {str(key): float(value) for key, value in data.items()}
        if not all(math.isfinite(value) for value in normalized.values()):
            raise ValueError("Adaptive detector input must be finite")
        return normalized

    def _score(self, data: dict[str, float]) -> float:
        score = float(self.pipeline.score_one(data))
        if not math.isfinite(score):
            raise ValueError("Aberrant returned a non-finite anomaly score")
        return score

    def _result(
        self,
        data: dict[str, float],
        score: float,
        is_anomaly: bool,
        phase: str,
        topic: str | None,
        charger_id: str | None,
        started: float,
    ) -> AnomalyResult:
        elapsed = time.time() - started
        self.processing_times.append(elapsed)
        threshold = self.threshold
        severity = "low"
        if is_anomaly:
            severity = (
                "high"
                if threshold is not None and score >= threshold * 1.5
                else "medium"
            )
        return AnomalyResult(
            anomaly_score=score,
            is_anomaly=is_anomaly,
            severity=severity,
            timestamp=datetime.now(UTC),
            model_info=self.get_model_info(),
            raw_data=data,
            processed_features=None,
            topic=topic,
            charger_id=charger_id,
            context={
                "processing_time_ms": elapsed * 1000,
                "model_type": self.adaptive_config.model_type,
                "adaptive_stream": {
                    "phase": phase,
                    "state": self.state.value,
                    "training_window_size": self.adaptive_config.training_window_size,
                    "calibration_window_size": (
                        self.adaptive_config.calibration_window_size
                    ),
                    "warmup_count": self.warmup_count,
                    "calibration_count": self.calibration_count,
                    "sequence_number": self.operational_count,
                    "anomaly_score": score,
                    "threshold": threshold,
                    "alarm_fired": is_anomaly,
                    "feature_keys": list(self.feature_keys),
                },
            },
        )

    def _checkpoint_model(self) -> None:
        try:
            manager = CheckpointManager()
            manager.save(
                {
                    "strategy": "adaptive_stream",
                    "adaptive_state": self.state.value,
                    "feature_keys": self.feature_keys,
                    "pipeline": self.pipeline,
                    "calibration_scores": self.calibration_scores,
                    "threshold": self.threshold,
                    "processed_count": self.processed_count,
                    "warmup_count": self.warmup_count,
                    "calibration_count": self.calibration_count,
                    "operational_count": self.operational_count,
                    "anomaly_count": self.anomaly_count,
                    "schema_mismatch_count": self.schema_mismatch_count,
                    "training_error": self.training_error,
                    "schema_signature": self.schema_signature,
                    "aberrant_version": ABERRANT_VERSION,
                    "service_id": manager.service_id,
                },
                processed_count=self.processed_count,
            )
            self.last_checkpoint = self.processed_count
        except Exception as exc:
            self.logger.error(
                "event=radar.adaptive_checkpoint_save_failed error=%s",
                exc,
                exc_info=True,
            )

    def get_model_info(self) -> dict[str, Any]:
        return {
            "strategy": "adaptive_stream",
            "state": self.state.value,
            "model_type": self.adaptive_config.model_type,
            "processed_count": self.processed_count,
            "warmup_count": self.warmup_count,
            "calibration_count": self.calibration_count,
            "operational_count": self.operational_count,
            "anomaly_count": self.anomaly_count,
            "training_window_size": self.adaptive_config.training_window_size,
            "calibration_window_size": self.adaptive_config.calibration_window_size,
            "threshold": self.threshold,
            "training_error": self.training_error,
            "schema_mismatch_count": self.schema_mismatch_count,
            "memory_usage_mb": self._memory_usage(),
            "avg_processing_time_ms": (
                sum(self.processing_times) / max(len(self.processing_times), 1) * 1000
            ),
            "uptime_seconds": time.time() - self.start_time,
        }

    @staticmethod
    def _memory_usage() -> float:
        try:
            return psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return 0.0

    def shutdown(self) -> None:
        """Adaptive models hold no background resources."""
