"""Aberrant-backed score-then-learn adaptive stream detector."""

import hashlib
import json
import logging
import math
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import numpy as np
import psutil
from aberrant import __version__ as aberrant_version
from aberrant.base import ModelProtocol
from aberrant.base.pipeline import ModelPipeline, Pipeline
from aberrant.catalog import DetectorConfig, WarmupUnit
from off_key_core.models import ABERRANT_VERSION
from off_key_core.schemas.radar import AdaptiveStreamConfig, IncrementalPCAConfig

from .checkpoint_manager import CheckpointManager
from .config.config import AnomalyDetectionConfig
from .models import AnomalyResult


@dataclass(frozen=True)
class _UnitInterval:
    """Bound scaled features, or reject out-of-domain raw features."""

    clip: bool

    def learn_one(self, x: dict[str, float]) -> None:
        self.transform_one(x)

    def transform_one(self, x: dict[str, float]) -> dict[str, float]:
        if self.clip:
            return {key: min(1.0, max(0.0, value)) for key, value in x.items()}
        if any(value < 0.0 or value > 1.0 for value in x.values()):
            raise ValueError(
                "This detector requires features in [0, 1]; configure min-max scaling"
            )
        return x


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
        if aberrant_version != ABERRANT_VERSION:
            raise ValueError(
                "RADAR runtime does not match its generated Aberrant catalog"
            )
        self.logger = logging.getLogger(__name__)
        self.detector_config = self._detector_config()
        self.detector_fingerprint = self.detector_config.fingerprint()
        self.model_capabilities = self.detector_config.capabilities().as_dict()
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
        # Validate constructors at startup, before subscribing or learning data.
        self.pipeline: ModelProtocol = self._build_pipeline(self.detector_config)
        self.calibration_scores: list[float] = []
        self.threshold: float | None = None
        self.severity_scale = 0.0
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
        self.detector_config = self._detector_config(self.feature_keys)
        self.detector_fingerprint = self.detector_config.fingerprint()
        self.model_capabilities = self.detector_config.capabilities().as_dict()
        if checkpoint.get("detector_fingerprint") != self.detector_fingerprint:
            raise ValueError(
                "Adaptive checkpoint detector configuration is incompatible"
            )
        if checkpoint.get("detector_config") != self.detector_config.as_dict():
            raise ValueError(
                "Adaptive checkpoint normalized configuration is incompatible"
            )
        self.pipeline = checkpoint["pipeline"]
        self.calibration_scores = list(checkpoint.get("calibration_scores", []))
        self.threshold = checkpoint.get("threshold")
        self.severity_scale = float(checkpoint["severity_scale"])
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
        if checkpoint.get("aberrant_version") != aberrant_version:
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
            "aberrant_version": aberrant_version,
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode()).hexdigest()

    def _detector_config(self, feature_keys: list[str] | None = None) -> DetectorConfig:
        detector_config = DetectorConfig.from_mapping(
            self.adaptive_config.detector_mapping(feature_keys)
        ).normalized()
        capabilities = detector_config.capabilities()
        if capabilities.higher_is_more_anomalous is not True:
            raise ValueError("RADAR requires higher scores to mean more anomalous")
        warmup = capabilities.warmup
        if warmup.unit != WarmupUnit.EVENTS or warmup.minimum is None:
            raise ValueError("RADAR requires a known warm-up in aligned observations")
        minimum = warmup.minimum
        for step in self.adaptive_config.preprocessing_steps:
            if isinstance(step, IncrementalPCAConfig):
                minimum = max(minimum, step.n0)
        if self.adaptive_config.training_window_size < minimum:
            raise ValueError(
                "training_window_size must cover model and preprocessing "
                f"warm-up ({minimum})"
            )
        return detector_config

    def _build_pipeline(self, detector_config: DetectorConfig) -> ModelProtocol:
        pipeline = detector_config.build()
        if detector_config.capabilities().requires_unit_interval:
            assert isinstance(pipeline, ModelPipeline)
            # MinMaxScaler can extrapolate before learning a new extreme. Clipping
            # is RADAR's explicit input-domain policy for unit-interval detectors.
            guard = _UnitInterval(clip=bool(self.adaptive_config.preprocessing_steps))
            pipeline = Pipeline(Pipeline(pipeline.first, guard), pipeline.second)
        return pipeline

    def _freeze_schema_and_build_pipeline(self, data: dict[str, float]) -> None:
        feature_keys = sorted(data)
        detector_config = self._detector_config(feature_keys)
        pipeline = self._build_pipeline(detector_config)
        self.feature_keys = feature_keys
        self.detector_config = detector_config
        self.detector_fingerprint = detector_config.fingerprint()
        self.model_capabilities = detector_config.capabilities().as_dict()
        self.pipeline = pipeline

    def process_data_point(
        self,
        data: dict[str, float],
        topic: str | None = None,
        charger_id: str | None = None,
    ) -> AnomalyResult:
        started = time.time()
        try:
            normalized = self._validate_data(data)
            if not self.feature_keys:
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
            self.severity_scale = max(
                abs(self.threshold),
                max(self.calibration_scores) - min(self.calibration_scores),
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
                if threshold is not None
                and self.severity_scale > 0
                and score - threshold >= self.severity_scale * 0.5
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
                    "detector_config": self.detector_config.as_dict(),
                    "detector_fingerprint": self.detector_fingerprint,
                    "severity_scale": self.severity_scale,
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
                    "aberrant_version": aberrant_version,
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
            "catalog_id": self.detector_config.model.id,
            "aberrant_version": aberrant_version,
            "detector_fingerprint": self.detector_fingerprint,
            "capabilities": self.model_capabilities,
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
