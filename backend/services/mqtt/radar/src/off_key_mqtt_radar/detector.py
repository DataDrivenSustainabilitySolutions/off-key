"""
MQTT RADAR Anomaly Detection Service

Implements anomaly detection patterns from guide.md for real-time processing
of MQTT telemetry data with resilient error handling and monitoring.
"""

import concurrent.futures
import hashlib
import json
import logging
import os
import re
import time
from collections import deque
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import numpy as np
import psutil

from .checkpoint_manager import CheckpointManager
from .config.config import AnomalyDetectionConfig
from .models import AnomalyResult

# =============================================================================
# Checkpoint Security
# =============================================================================

_UNSEEN_FEATURE_PATTERN = re.compile(
    r"Feature ['\"](?P<feature>[^'\"]+)['\"] has not been seen during learning"
)
_WARMUP_STAGE_PATTERN = re.compile(r"^(?P<stage>[a-z_]+):\s")


class StaticConformalState(Enum):
    """Lifecycle states for static conformal monitoring."""

    COLLECTING = "collecting"
    CALIBRATING = "calibrating"
    TRAINING = "training"
    READY = "ready"
    FAILED = "failed"


class RestartedMartingaleAlarmController:
    """Power e-process using nonconform's native restarted mixture."""

    FIXED_RESTARTED_VILLE_THRESHOLD = 100.0

    def __init__(
        self,
        *,
        epsilon: float,
        restarted_ville_threshold: float = FIXED_RESTARTED_VILLE_THRESHOLD,
        alarm_count: int = 0,
        tested_count: int = 0,
        martingale: Any = None,
        alarm_active: bool = False,
    ):
        self.method = "power"
        self.epsilon = float(epsilon)
        self._validate_threshold(restarted_ville_threshold)
        self.restarted_ville_threshold = float(restarted_ville_threshold)
        self.alarm_count = int(alarm_count)
        self.tested_count = int(tested_count)
        self._alarm_active = bool(alarm_active)
        self._martingale = martingale or self._new_martingale()

    @classmethod
    def from_config(cls, config: Any) -> "RestartedMartingaleAlarmController":
        return cls(
            epsilon=config.epsilon,
            restarted_ville_threshold=config.restarted_ville_threshold,
        )

    @classmethod
    def _validate_threshold(cls, value: float) -> None:
        if float(value) != cls.FIXED_RESTARTED_VILLE_THRESHOLD:
            raise ValueError(
                "restarted_ville_threshold is fixed at "
                f"{cls.FIXED_RESTARTED_VILLE_THRESHOLD:g}."
            )

    def _new_martingale(self) -> Any:
        from nonconform.martingales import AlarmConfig, PowerMartingale

        return PowerMartingale(
            epsilon=self.epsilon,
            alarm_config=AlarmConfig(
                restarted_ville_threshold=self.restarted_ville_threshold
            ),
        )

    def update(self, p_value: float) -> dict[str, Any]:
        state = self._martingale.update(p_value)
        self.tested_count += 1
        threshold_crossed = (
            "restarted_ville" in state.triggered_alarms
            or state.restarted_martingale >= self.restarted_ville_threshold
        )
        alarm_fired = threshold_crossed and not self._alarm_active
        self._alarm_active = threshold_crossed
        if alarm_fired:
            self.alarm_count += 1

        if p_value == 0.0:
            log_e_value = float("inf") if self.epsilon < 1.0 else 0.0
        else:
            log_e_value = float(
                np.log(self.epsilon) + (self.epsilon - 1.0) * np.log(p_value)
            )
        max_log_float = float(np.log(np.finfo(float).max))
        e_value = (
            float(np.exp(log_e_value))
            if np.isfinite(log_e_value) and log_e_value <= max_log_float
            else float("inf")
        )
        finite_e_value = e_value if np.isfinite(e_value) else None
        restarted_martingale = float(state.restarted_martingale)
        finite_restarted_martingale = (
            restarted_martingale if np.isfinite(restarted_martingale) else None
        )
        log_restarted_martingale = float(state.log_restarted_martingale)
        finite_log_restarted_martingale = (
            log_restarted_martingale if np.isfinite(log_restarted_martingale) else None
        )
        context = {
            "martingale_method": self.method,
            "epsilon": self.epsilon,
            "e_value": finite_e_value,
            "e_value_is_infinite": finite_e_value is None,
            "log_e_value": log_e_value if np.isfinite(log_e_value) else None,
            "restarted_ville_threshold": self.restarted_ville_threshold,
            "restarted_martingale": finite_restarted_martingale,
            "restarted_martingale_is_infinite": (finite_restarted_martingale is None),
            "log_restarted_martingale": finite_log_restarted_martingale,
            "alarm_fired": alarm_fired,
            "alarm_active": self._alarm_active,
            "alarm_count": self.alarm_count,
            "tested_count": self.tested_count,
        }
        return context


class StaticConformalDetectionService:
    """Train-once static baseline detector using conformal p-values and martingales."""

    def __init__(
        self,
        config: AnomalyDetectionConfig,
        checkpoint: dict[str, Any] | None = None,
    ):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.schema_signature = self._build_schema_signature_from_config(config)
        self.static_config = config.static_baseline_config
        self.start_time = time.time()
        self.processing_times: deque = deque(maxlen=1000)
        self._training_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self._training_future: concurrent.futures.Future | None = None
        self.training_error: str | None = None

        if checkpoint:
            self._restore_from_checkpoint(checkpoint)
        else:
            self._initialize_fresh()

        self.logger.info(
            "Initialized static conformal detection service with model: %s "
            "(restored=%s)",
            config.model_type,
            checkpoint is not None,
        )

    def _initialize_fresh(self) -> None:
        self.state = StaticConformalState.COLLECTING
        self.training_buffer: list[dict[str, float]] = []
        self.calibration_buffer: list[dict[str, float]] = []
        self.feature_keys: list[str] = []
        self.conformal_detector = None
        self.alarm_controller = self._create_alarm_controller()
        self.processed_count = 0
        self.anomaly_count = 0
        self.last_checkpoint = 0
        self.discarded_during_training_count = 0
        self.schema_mismatch_count = 0

    def shutdown(self) -> None:
        """Stop background static-baseline training resources."""
        if self._training_future is not None and not self._training_future.done():
            self._training_future.cancel()
        self._training_executor.shutdown(wait=False, cancel_futures=True)

    def _restore_from_checkpoint(self, checkpoint: dict[str, Any]) -> None:
        self.state = StaticConformalState(
            checkpoint.get("static_state", StaticConformalState.COLLECTING.value)
        )
        self.training_buffer = list(checkpoint.get("training_buffer", []))
        self.calibration_buffer = list(checkpoint.get("calibration_buffer", []))
        self.feature_keys = list(checkpoint.get("feature_keys", []))
        self.conformal_detector = checkpoint.get("conformal_detector")
        self.alarm_controller = checkpoint.get("alarm_controller")
        if not isinstance(self.alarm_controller, RestartedMartingaleAlarmController):
            raise ValueError(
                "Static checkpoint is missing a valid alarm_controller. "
                "Starting fresh is required."
            )
        self.processed_count = int(checkpoint.get("processed_count", 0))
        self.anomaly_count = int(checkpoint.get("anomaly_count", 0))
        self.last_checkpoint = self.processed_count
        self.discarded_during_training_count = int(
            checkpoint.get("discarded_during_training_count", 0)
        )
        self.schema_mismatch_count = int(checkpoint.get("schema_mismatch_count", 0))
        self.training_error = checkpoint.get("training_error")
        if self.state == StaticConformalState.TRAINING:
            # Training futures cannot be restored; restart collection rather than
            # treating a half-trained checkpoint as ready.
            self.state = StaticConformalState.COLLECTING
            self.training_buffer = []
            self.calibration_buffer = []

        if self.state == StaticConformalState.READY:
            missing_ready_state = []
            if not self.feature_keys:
                missing_ready_state.append("feature_keys")
            if self.conformal_detector is None:
                missing_ready_state.append("conformal_detector")
            if missing_ready_state:
                missing = ", ".join(missing_ready_state)
                raise ValueError(
                    "Static checkpoint is marked ready but is missing required "
                    f"state: {missing}. Starting fresh is required."
                )

        self.logger.info(
            "Restored static conformal checkpoint: state=%s processed=%s "
            "anomalies=%s feature_count=%s",
            self.state.value,
            self.processed_count,
            self.anomaly_count,
            len(self.feature_keys),
        )

    @classmethod
    def from_checkpoint(
        cls, checkpoint_path: str, config: AnomalyDetectionConfig
    ) -> "StaticConformalDetectionService":
        checkpoint = CheckpointManager().load(checkpoint_path)

        saved_strategy = checkpoint.get("strategy")
        if saved_strategy != "static_baseline":
            raise ValueError(
                "Checkpoint strategy does not match static_baseline configuration."
            )

        saved_schema_signature = checkpoint.get("schema_signature")
        current_schema_signature = cls._build_schema_signature_from_config(config)
        if saved_schema_signature != current_schema_signature:
            raise ValueError(
                "Checkpoint schema signature does not match current static "
                "configuration. Starting fresh is required."
            )

        return cls(config, checkpoint=checkpoint)

    @classmethod
    def _build_schema_signature_from_config(cls, config: Any) -> str:
        static_config = getattr(config, "static_baseline_config", None)
        if static_config is not None and hasattr(static_config, "model_dump"):
            static_payload = static_config.model_dump(exclude_none=True)
        else:
            static_payload = {}
        return cls._build_static_schema_signature(config, static_payload)

    @classmethod
    def _build_static_schema_signature(
        cls, config: Any, static_payload: dict[str, Any]
    ) -> str:
        subscription_topics = [
            str(topic)
            for topic in (getattr(config, "subscription_topics", []) or [])
            if topic is not None
        ]
        payload = {
            "strategy": "static_baseline",
            "model_type": str(
                static_payload.get("model_type", getattr(config, "model_type", ""))
            ),
            "model_params": static_payload.get(
                "model_params", getattr(config, "model_params", {}) or {}
            ),
            "static_baseline_config": static_payload,
            "subscription_topics": sorted(subscription_topics),
            "sensor_key_strategy": str(
                getattr(config, "sensor_key_strategy", "full_hierarchy")
            ),
            "alignment_mode": str(getattr(config, "alignment_mode", "strict_barrier")),
        }
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

    def process_data_point(
        self, data: dict[str, float], topic: str = None, charger_id: str = None
    ) -> AnomalyResult:
        start_time = time.time()
        self._complete_training_if_ready()

        if self.state == StaticConformalState.COLLECTING:
            result = self._process_collecting(data, topic, charger_id, start_time)
        elif self.state == StaticConformalState.CALIBRATING:
            result = self._process_calibrating(data, topic, charger_id, start_time)
        elif self.state == StaticConformalState.TRAINING:
            result = self._process_training(data, topic, charger_id, start_time)
        elif self.state == StaticConformalState.READY:
            result = self._process_ready(data, topic, charger_id, start_time)
        else:
            result = self._process_failed(data, topic, charger_id, start_time)

        should_checkpoint = (
            self.processed_count
            and self.processed_count % self.config.checkpoint_interval == 0
        )
        if should_checkpoint:
            self._checkpoint_model()
        return result

    def _process_collecting(
        self,
        data: dict[str, float],
        topic: str | None,
        charger_id: str | None,
        start_time: float,
    ) -> AnomalyResult:
        schema_error = self._validate_or_freeze_feature_schema(data)
        self.processed_count += 1

        if schema_error:
            self.schema_mismatch_count += 1
            return self._build_result(
                data=data,
                processed_features=None,
                score=1.0,
                is_anomaly=False,
                severity="low",
                topic=topic,
                charger_id=charger_id,
                start_time=start_time,
                phase="schema_mismatch",
                extra_context={"schema_error": schema_error},
            )

        self.training_buffer.append(
            {key: float(data[key]) for key in self.feature_keys}
        )
        collected = len(self.training_buffer)
        if collected >= self.static_config.training_window_size:
            self.state = StaticConformalState.CALIBRATING
            phase = "calibrating"
        else:
            phase = "collecting"

        return self._build_result(
            data=data,
            processed_features=data,
            score=1.0,
            is_anomaly=False,
            severity="low",
            topic=topic,
            charger_id=charger_id,
            start_time=start_time,
            phase=phase,
            extra_context={"training_collected_samples": collected},
        )

    def _process_calibrating(
        self,
        data: dict[str, float],
        topic: str | None,
        charger_id: str | None,
        start_time: float,
    ) -> AnomalyResult:
        schema_error = self._validate_or_freeze_feature_schema(data)
        self.processed_count += 1

        if schema_error:
            self.schema_mismatch_count += 1
            return self._build_result(
                data=data,
                processed_features=None,
                score=1.0,
                is_anomaly=False,
                severity="low",
                topic=topic,
                charger_id=charger_id,
                start_time=start_time,
                phase="schema_mismatch",
                extra_context={"schema_error": schema_error},
            )

        self.calibration_buffer.append(
            {key: float(data[key]) for key in self.feature_keys}
        )
        calibration_collected = len(self.calibration_buffer)
        if calibration_collected >= self.static_config.calibration_window_size:
            training_samples = list(self.training_buffer)
            calibration_samples = list(self.calibration_buffer)
            self.training_buffer = []
            self.calibration_buffer = []
            self.state = StaticConformalState.TRAINING
            self._training_future = self._training_executor.submit(
                self._fit_static_baseline,
                training_samples,
                calibration_samples,
                list(self.feature_keys),
            )
            phase = "training_started"
        else:
            phase = "calibrating"

        return self._build_result(
            data=data,
            processed_features=data,
            score=1.0,
            is_anomaly=False,
            severity="low",
            topic=topic,
            charger_id=charger_id,
            start_time=start_time,
            phase=phase,
            extra_context={"calibration_collected_samples": calibration_collected},
        )

    def _process_training(
        self,
        data: dict[str, float],
        topic: str | None,
        charger_id: str | None,
        start_time: float,
    ) -> AnomalyResult:
        self.processed_count += 1
        self.discarded_during_training_count += 1
        return self._build_result(
            data=data,
            processed_features=None,
            score=1.0,
            is_anomaly=False,
            severity="low",
            topic=topic,
            charger_id=charger_id,
            start_time=start_time,
            phase="training_discarded",
            extra_context={
                "discarded_during_training_count": (
                    self.discarded_during_training_count
                )
            },
        )

    def _process_ready(
        self,
        data: dict[str, float],
        topic: str | None,
        charger_id: str | None,
        start_time: float,
    ) -> AnomalyResult:
        schema_error = self._validate_or_freeze_feature_schema(data)
        self.processed_count += 1
        if schema_error:
            self.schema_mismatch_count += 1
            return self._build_result(
                data=data,
                processed_features=None,
                score=1.0,
                is_anomaly=False,
                severity="low",
                topic=topic,
                charger_id=charger_id,
                start_time=start_time,
                phase="schema_mismatch",
                extra_context={"schema_error": schema_error},
            )

        vector = self._vectorize(data)
        p_value = self._compute_p_value(vector)
        if self.alarm_controller is None:
            self.alarm_controller = self._create_alarm_controller()
        alarm_context = self.alarm_controller.update(p_value)
        is_anomaly = bool(alarm_context["alarm_fired"])
        if is_anomaly:
            self.anomaly_count += 1
        severity = self._calculate_conformal_severity(
            p_value,
            is_anomaly,
            1.0 / float(alarm_context["restarted_ville_threshold"]),
        )

        result = self._build_result(
            data=data,
            processed_features={
                key: vector[index] for index, key in enumerate(self.feature_keys)
            },
            score=p_value,
            is_anomaly=is_anomaly,
            severity=severity,
            topic=topic,
            charger_id=charger_id,
            start_time=start_time,
            phase="ready",
            extra_context={
                "p_value": p_value,
                **alarm_context,
            },
        )

        if is_anomaly:
            self.logger.warning(
                "event=radar.static_conformal_martingale_alarm p_value=%.6f "
                "restarted_martingale=%s severity=%s topic=%s",
                p_value,
                alarm_context["restarted_martingale"] or "inf",
                severity,
                topic,
                extra={
                    "conformal_pvalue": p_value,
                    "martingale_method": alarm_context["martingale_method"],
                    "restarted_ville_threshold": (
                        alarm_context["restarted_ville_threshold"]
                    ),
                    "alarm_count": alarm_context["alarm_count"],
                    "model_type": self.config.model_type,
                    "charger_id": charger_id,
                },
            )
        return result

    def _process_failed(
        self,
        data: dict[str, float],
        topic: str | None,
        charger_id: str | None,
        start_time: float,
    ) -> AnomalyResult:
        self.processed_count += 1
        return self._build_result(
            data=data,
            processed_features=None,
            score=1.0,
            is_anomaly=False,
            severity="unknown",
            topic=topic,
            charger_id=charger_id,
            start_time=start_time,
            phase="failed",
            extra_context={"training_error": self.training_error},
        )

    def _validate_or_freeze_feature_schema(self, data: dict[str, float]) -> str | None:
        keys = sorted(data.keys())
        if not keys:
            return "empty feature vector"
        if not self.feature_keys:
            self.feature_keys = keys
            return None
        if keys != self.feature_keys:
            missing = sorted(set(self.feature_keys) - set(keys))
            extra = sorted(set(keys) - set(self.feature_keys))
            return f"feature schema mismatch missing={missing} extra={extra}"
        return None

    def _vectorize(self, data: dict[str, float]) -> list[float]:
        return [float(data[key]) for key in self.feature_keys]

    def _fit_static_baseline(
        self,
        training_samples: list[dict[str, float]],
        calibration_samples: list[dict[str, float]],
        feature_keys: list[str],
    ) -> tuple[Any, Any]:
        from nonconform import ConformalDetector, Split

        detector = self._create_pyod_detector()
        training_matrix = np.asarray(
            [
                [float(sample[key]) for key in feature_keys]
                for sample in training_samples
            ],
            dtype=float,
        )
        calibration_matrix = np.asarray(
            [
                [float(sample[key]) for key in feature_keys]
                for sample in calibration_samples
            ],
            dtype=float,
        )
        detector.fit(training_matrix)
        conformal_detector = ConformalDetector(
            detector=detector,
            strategy=Split(n_calib=0.1),
            score_polarity="auto",
            seed=self.static_config.seed,
        )
        conformal_detector.calibrate(calibration_matrix)

        alarm_controller = self._create_alarm_controller()
        return conformal_detector, alarm_controller

    def _create_alarm_controller(self) -> RestartedMartingaleAlarmController:
        martingale_config = self.static_config.martingale_config
        return RestartedMartingaleAlarmController(
            epsilon=martingale_config.epsilon,
            restarted_ville_threshold=(martingale_config.restarted_ville_threshold),
        )

    def _create_pyod_detector(self) -> Any:
        model_type = self.static_config.model_type
        params = dict(self.static_config.model_params or {})
        if self.static_config.seed is not None:
            params.setdefault("random_state", self.static_config.seed)

        return self._instantiate_pyod_detector(model_type, params)

    def _instantiate_pyod_detector(
        self, model_type: str, params: dict[str, Any]
    ) -> Any:
        if model_type == "pyod_iforest":
            from pyod.models.iforest import IForest

            return IForest(**params)
        if model_type == "pyod_knn":
            params.pop("random_state", None)
            from pyod.models.knn import KNN

            return KNN(**params)
        if model_type == "pyod_lof":
            params.pop("random_state", None)
            from pyod.models.lof import LOF

            return LOF(**params)
        if model_type == "pyod_ocsvm":
            params.pop("random_state", None)
            from pyod.models.ocsvm import OCSVM

            return OCSVM(**params)
        if model_type == "pyod_hbos":
            params.pop("random_state", None)
            from pyod.models.hbos import HBOS

            return HBOS(**params)
        if model_type == "pyod_pca":
            params.pop("random_state", None)
            from pyod.models.pca import PCA

            return PCA(**params)

        raise ValueError(
            f"Unsupported static PyOD model '{model_type}'. "
            "Expected one of pyod_iforest, pyod_knn, pyod_lof, pyod_ocsvm, "
            "pyod_hbos, pyod_pca."
        )

    def _complete_training_if_ready(self) -> None:
        if self.state != StaticConformalState.TRAINING or self._training_future is None:
            return
        if not self._training_future.done():
            return

        try:
            (
                self.conformal_detector,
                self.alarm_controller,
            ) = self._training_future.result()
            self.state = StaticConformalState.READY
            self.training_error = None
            self._checkpoint_model()
            self.logger.info(
                "event=radar.static_conformal_training_complete "
                "training_window_size=%s calibration_window_size=%s "
                "feature_count=%s",
                self.static_config.training_window_size,
                self.static_config.calibration_window_size,
                len(self.feature_keys),
            )
        except Exception as exc:
            self.state = StaticConformalState.FAILED
            self.training_error = str(exc)
            self.logger.error(
                "event=radar.static_conformal_training_failed error=%s",
                str(exc),
                exc_info=True,
            )
        finally:
            self._training_future = None

    def refresh_background_state(self) -> None:
        """Publish completed background training without waiting for new input."""
        self._complete_training_if_ready()

    def _compute_p_value(self, vector: list[float]) -> float:
        p_values = np.asarray(
            self.conformal_detector.compute_p_values(np.asarray([vector], dtype=float)),
            dtype=float,
        ).reshape(-1)
        if p_values.size != 1:
            raise ValueError(
                "Static conformal detector must return exactly one p-value "
                f"for one inference sample; got {p_values.size}."
            )
        p_value = float(p_values[0])
        if not np.isfinite(p_value):
            raise ValueError("Static conformal detector returned a non-finite p-value.")
        if not 0.0 <= p_value <= 1.0:
            raise ValueError(
                "Static conformal detector returned a p-value outside [0, 1]: "
                f"{p_value}."
            )
        return p_value

    def _calculate_conformal_severity(
        self, p_value: float, is_anomaly: bool, threshold: float
    ) -> str:
        if not is_anomaly:
            return "low"
        if p_value <= threshold / 20.0:
            return "critical"
        if p_value <= threshold / 5.0:
            return "high"
        return "medium"

    def _build_result(
        self,
        *,
        data: dict[str, float],
        processed_features: dict[str, float] | None,
        score: float,
        is_anomaly: bool,
        severity: str,
        topic: str | None,
        charger_id: str | None,
        start_time: float,
        phase: str,
        extra_context: dict[str, Any] | None = None,
    ) -> AnomalyResult:
        processing_time = time.time() - start_time
        self.processing_times.append(processing_time)
        context = {
            "processing_time_ms": processing_time * 1000,
            "model_type": self.config.model_type,
            "static_conformal": {
                "phase": phase,
                "state": self.state.value,
                "training_window_size": self.static_config.training_window_size,
                "calibration_window_size": (self.static_config.calibration_window_size),
                "collected_samples": len(self.training_buffer),
                "training_collected_samples": len(self.training_buffer),
                "calibration_collected_samples": len(self.calibration_buffer),
                "feature_keys": list(self.feature_keys),
                "discarded_during_training_count": (
                    self.discarded_during_training_count
                ),
                "schema_mismatch_count": self.schema_mismatch_count,
                **(extra_context or {}),
            },
        }
        return AnomalyResult(
            anomaly_score=score,
            is_anomaly=is_anomaly,
            severity=severity,
            timestamp=datetime.now(UTC),
            model_info=self.get_model_info(),
            raw_data=data,
            processed_features=processed_features,
            topic=topic,
            charger_id=charger_id,
            context=context,
        )

    def _checkpoint_model(self) -> None:
        try:
            checkpoint_manager = CheckpointManager()
            service_id = checkpoint_manager.service_id
            checkpoint_data = {
                "strategy": "static_baseline",
                "static_state": self.state.value,
                "training_buffer": self.training_buffer,
                "calibration_buffer": self.calibration_buffer,
                "feature_keys": self.feature_keys,
                "conformal_detector": self.conformal_detector,
                "alarm_controller": self.alarm_controller,
                "processed_count": self.processed_count,
                "anomaly_count": self.anomaly_count,
                "discarded_during_training_count": (
                    self.discarded_during_training_count
                ),
                "schema_mismatch_count": self.schema_mismatch_count,
                "training_error": self.training_error,
                "config": self.config,
                "service_id": service_id,
                "schema_signature": self.schema_signature,
            }

            checkpoint_path = checkpoint_manager.save(
                checkpoint_data,
                processed_count=self.processed_count,
            )
            self.logger.info(
                "Static conformal checkpoint saved atomically: %s",
                checkpoint_path,
            )
        except Exception as exc:
            self.logger.error(
                "event=radar.static_conformal_checkpoint_save_failed error=%s",
                str(exc),
                exc_info=True,
            )

    def get_model_info(self) -> dict[str, Any]:
        return {
            "strategy": "static_baseline",
            "state": self.state.value,
            "processed_count": self.processed_count,
            "anomaly_count": self.anomaly_count,
            "anomaly_rate": self.anomaly_count / max(self.processed_count, 1),
            "training_window_size": self.static_config.training_window_size,
            "calibration_window_size": self.static_config.calibration_window_size,
            "collected_samples": len(self.training_buffer),
            "training_collected_samples": len(self.training_buffer),
            "calibration_collected_samples": len(self.calibration_buffer),
            "training_error": self.training_error,
            "alarm_count": (
                self.alarm_controller.alarm_count
                if self.alarm_controller is not None
                else 0
            ),
            "tested_count": (
                self.alarm_controller.tested_count
                if self.alarm_controller is not None
                else 0
            ),
            "discarded_during_training_count": self.discarded_during_training_count,
            "schema_mismatch_count": self.schema_mismatch_count,
            "memory_usage_mb": self._get_memory_usage(),
            "avg_processing_time_ms": sum(self.processing_times)
            / max(len(self.processing_times), 1)
            * 1000,
            "uptime_seconds": time.time() - self.start_time,
        }

    def _get_memory_usage(self) -> float:
        try:
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / 1024 / 1024
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return 0.0
