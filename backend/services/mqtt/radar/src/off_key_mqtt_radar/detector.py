"""
MQTT RADAR Anomaly Detection Service

Implements anomaly detection patterns from guide.md for real-time processing
of MQTT telemetry data with resilient error handling and monitoring.
"""

import logging
import time
import pickle
import os
import psutil
import gc
import hashlib
import hmac
import re
import json
import concurrent.futures
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from collections import deque
from enum import Enum

import numpy as np

# Model registry for dynamic model loading
from .tactic_client import (
    create_model_instance,
    validate_preprocessing_steps,
    get_preprocessor_class,
)

from .config.config import AnomalyDetectionConfig
from .config.runtime import get_radar_checkpoint_settings
from .models import AnomalyResult


# =============================================================================
# Checkpoint Security
# =============================================================================

_checkpoint_secret_warning_logged = False
_UNSEEN_FEATURE_PATTERN = re.compile(
    r"Feature ['\"](?P<feature>[^'\"]+)['\"] has not been seen during learning"
)
_WARMUP_STAGE_PATTERN = re.compile(r"^(?P<stage>[a-z_]+):\s")
_DEFAULT_METADATA_FEATURE_KEYS = frozenset(
    {
        "timestamp",
        "time",
        "datetime",
        "date",
        "created",
        "created_at",
        "updated_at",
        "ingested_at",
    }
)


def _get_checkpoint_secret() -> bytes:
    """Get checkpoint signing secret from runtime configuration."""
    return get_radar_checkpoint_settings().checkpoint_secret_bytes


def _sign_checkpoint_data(data: bytes) -> str:
    """Create HMAC signature for checkpoint data."""
    secret = _get_checkpoint_secret()
    if not secret:
        return ""
    return hmac.new(secret, data, hashlib.sha256).hexdigest()


def _verify_checkpoint_signature(data: bytes, signature: str) -> bool:
    """Verify HMAC signature for checkpoint data.

    If no secret is configured, verification is skipped (returns True).
    This allows backwards compatibility with unsigned checkpoints in dev.
    """
    global _checkpoint_secret_warning_logged
    logger = logging.getLogger(__name__)

    secret = _get_checkpoint_secret()
    if not secret:
        # Log warning once per process to avoid spam
        if not _checkpoint_secret_warning_logged:
            logger.warning(
                "RADAR_CHECKPOINT_SECRET not configured - checkpoint signature "
                "verification is DISABLED. Set this environment variable in "
                "production to protect against checkpoint tampering."
            )
            _checkpoint_secret_warning_logged = True
        return True  # Skip verification if no secret configured
    if not signature:
        return False  # Signature required when secret is set
    expected = hmac.new(secret, data, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


class ServiceState(Enum):
    """Service health states"""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class AnomalyDetectionService:
    """
    Core anomaly detection service following guide.md patterns

    Implements:
    - Multiple model support (Isolation Forest, SVM, KNN)
    - Preprocessing pipeline
    - Memory management
    - Model checkpointing
    - Performance monitoring
    """

    def __init__(
        self,
        config: AnomalyDetectionConfig,
        checkpoint: Optional[Dict[str, Any]] = None,
    ):
        """Initialize anomaly detection service.

        Args:
            config: Service configuration
            checkpoint: Optional checkpoint data to restore from. If provided,
                       the model and preprocessors are restored from the checkpoint
                       instead of being created fresh.
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.schema_signature = self._build_schema_signature_from_config(config)

        # Performance tracking (always fresh)
        self.start_time = time.time()
        self.processing_times: deque = deque(maxlen=1000)

        if checkpoint:
            self._restore_from_checkpoint(checkpoint)
        else:
            self._initialize_fresh()

        self.logger.info(
            f"Initialized anomaly detection service with model: {config.model_type}"
            f" (restored={checkpoint is not None})"
        )

    def _initialize_fresh(self):
        """Initialize fresh model and preprocessors."""
        self.model = self._create_model()
        self.preprocessors = self._create_preprocessors()
        self.processed_count = 0
        self.anomaly_count = 0
        self.last_checkpoint = 0
        self.score_window = deque(maxlen=self._get_heuristic_window_size())
        self.skipped_learning_anomaly_count = 0
        self.pre_ready_suppressed_count = 0

    def _restore_from_checkpoint(self, checkpoint: Dict[str, Any]):
        """Restore state from checkpoint data."""
        self.model = checkpoint["model"]
        self.preprocessors = checkpoint.get("preprocessors", [])
        self.processed_count = checkpoint["processed_count"]
        self.anomaly_count = checkpoint["anomaly_count"]
        self.last_checkpoint = self.processed_count
        self.schema_signature = checkpoint["schema_signature"]
        self.skipped_learning_anomaly_count = int(
            checkpoint.get("skipped_learning_anomaly_count", 0)
        )
        self.pre_ready_suppressed_count = int(
            checkpoint.get("pre_ready_suppressed_count", 0)
        )
        self.score_window = deque(
            (
                float(v)
                for v in checkpoint.get("score_window", [])
                if isinstance(v, (int, float))
            ),
            maxlen=self._get_heuristic_window_size(),
        )

        self.logger.info(
            f"Restored from checkpoint: {self.processed_count} points processed, "
            f"{self.anomaly_count} anomalies detected, "
            f"{len(self.preprocessors)} preprocessors restored"
        )

    @classmethod
    def _load_and_verify_checkpoint(cls, checkpoint_path: str) -> Dict[str, Any]:
        """Load checkpoint file with signature verification.

        Args:
            checkpoint_path: Path to the checkpoint file

        Returns:
            Verified checkpoint data

        Raises:
            ValueError: If signature verification fails
            FileNotFoundError: If checkpoint file doesn't exist
        """
        logger = logging.getLogger(__name__)

        # Read raw bytes for signature verification
        with open(checkpoint_path, "rb") as f:
            raw_data = f.read()

        # Check for signature file
        sig_path = checkpoint_path + ".sig"
        signature = ""
        if os.path.exists(sig_path):
            with open(sig_path, "r") as f:
                signature = f.read().strip()

        # Verify signature
        if not _verify_checkpoint_signature(raw_data, signature):
            logger.error(f"Checkpoint signature verification failed: {checkpoint_path}")
            raise ValueError(
                f"Checkpoint signature verification failed. "
                f"The checkpoint file may have been tampered with: {checkpoint_path}"
            )

        # Deserialize after verification
        return pickle.loads(raw_data)

    @classmethod
    def from_checkpoint(
        cls, checkpoint_path: str, config: AnomalyDetectionConfig
    ) -> "AnomalyDetectionService":
        """Restore service from a checkpoint file.

        This restores the learned state of both the model and preprocessors,
        allowing the service to resume from where it left off.

        Args:
            checkpoint_path: Path to the pickle checkpoint file
            config: Current configuration (used for runtime behavior and validation)

        Returns:
            Restored AnomalyDetectionService instance

        Raises:
            ValueError: If checkpoint signature fails or model type mismatches
        """
        logger = logging.getLogger(__name__)

        # Load and verify checkpoint
        checkpoint = cls._load_and_verify_checkpoint(checkpoint_path)

        # Validate model type matches
        saved_config = checkpoint.get("config")
        if (
            saved_config
            and hasattr(saved_config, "model_type")
            and saved_config.model_type != config.model_type
        ):
            raise ValueError(
                f"Checkpoint model type '{saved_config.model_type}' "
                f"does not match config model type '{config.model_type}'."
            )

        saved_schema_signature = checkpoint.get("schema_signature")
        if not saved_schema_signature:
            raise ValueError(
                "Checkpoint is missing a schema signature. "
                "This checkpoint format is no longer supported."
            )

        current_schema_signature = cls._build_schema_signature_from_config(config)
        if saved_schema_signature != current_schema_signature:
            raise ValueError(
                "Checkpoint schema signature does not match current configuration. "
                "Starting with a fresh model is required."
            )

        logger.info(f"Loading verified checkpoint: {checkpoint_path}")
        return cls(config, checkpoint=checkpoint)

    @staticmethod
    def _normalize_preprocessing_steps_for_signature(
        preprocessing_steps: Any,
    ) -> List[Dict[str, Any]]:
        """Normalize preprocessing definition into a stable, serializable structure."""
        normalized_steps: List[Dict[str, Any]] = []
        if not isinstance(preprocessing_steps, list):
            return normalized_steps

        for step in preprocessing_steps:
            if not isinstance(step, dict):
                continue
            step_type = str(step.get("type", ""))
            params = step.get("params") or {}
            if not isinstance(params, dict):
                params = {}
            normalized_steps.append({"type": step_type, "params": params})

        return normalized_steps

    @classmethod
    def _build_schema_signature_from_config(cls, config: Any) -> str:
        """Compute a stable schema signature for checkpoint compatibility checks."""
        model_type = str(getattr(config, "model_type", ""))
        preprocessing_steps = cls._normalize_preprocessing_steps_for_signature(
            getattr(config, "preprocessing_steps", [])
        )
        subscription_topics = [
            str(topic)
            for topic in (getattr(config, "subscription_topics", []) or [])
            if topic is not None
        ]
        sensor_key_strategy = str(
            getattr(config, "sensor_key_strategy", "full_hierarchy")
        )
        alignment_mode = str(getattr(config, "alignment_mode", "strict_barrier"))
        heuristic_enabled = bool(getattr(config, "heuristic_enabled", True))
        heuristic_window_size = int(getattr(config, "heuristic_window_size", 300))
        heuristic_min_samples = int(getattr(config, "heuristic_min_samples", 30))
        heuristic_tail_alpha = float(getattr(config, "heuristic_tail_alpha", 0.005))
        skip_learning_on_anomaly = True
        threshold_method = "tail_probability"

        payload = {
            "model_type": model_type,
            "preprocessing_steps": preprocessing_steps,
            "subscription_topics": sorted(subscription_topics),
            "sensor_key_strategy": sensor_key_strategy,
            "alignment_mode": alignment_mode,
            "heuristic_enabled": heuristic_enabled,
            "heuristic_window_size": heuristic_window_size,
            "heuristic_min_samples": heuristic_min_samples,
            "heuristic_tail_alpha": heuristic_tail_alpha,
            "skip_learning_on_anomaly": skip_learning_on_anomaly,
            "threshold_method": threshold_method,
        }
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

    def _create_model(self):
        """Factory method for model creation using registry.

        Uses create_model_instance which handles special cases like KNN
        that require additional setup (e.g., similarity engine).
        """
        try:
            # Log params before validation
            self.logger.info(
                "event=radar.model_create type=%s params=%s",
                self.config.model_type,
                self.config.model_params,
            )

            # Use create_model_instance which handles special cases like KNN
            return create_model_instance(
                self.config.model_type, self.config.model_params
            )

        except ImportError as e:
            self.logger.error(
                "event=radar.model_import_failed error=%s",
                str(e),
                exc_info=True,
            )
            raise
        except ValueError as e:
            self.logger.error(
                "event=radar.model_config_invalid error=%s",
                str(e),
                exc_info=True,
            )
            raise

    def _create_preprocessors(self):
        """Create preprocessing pipeline from validated config."""
        preprocessors = []
        try:
            validated_steps = validate_preprocessing_steps(
                getattr(self.config, "preprocessing_steps", [])
            )
            for step in validated_steps:
                preprocessor_cls = get_preprocessor_class(step["type"])
                preprocessors.append(preprocessor_cls(**step.get("params", {})))
            if preprocessors:
                step_types = [s["type"] for s in validated_steps]
                self.logger.info(
                    "event=radar.preprocessing_enabled steps=%s",
                    step_types,
                )
        except Exception as e:
            self.logger.error(
                "event=radar.preprocessing_create_failed error=%s",
                str(e),
                exc_info=True,
            )
            raise

        return preprocessors

    def _transform_pipeline(self, sample: Dict[str, float]) -> Dict[str, float]:
        """Apply the preprocessing pipeline using current learned state."""
        transformed = sample.copy()
        for preprocessor in self.preprocessors:
            transformed = preprocessor.transform_one(transformed)
        return transformed

    def _learn_pipeline(self, sample: Dict[str, float]) -> None:
        """Learn preprocessors stage-by-stage using each stage's transformed output."""
        stage_input = sample.copy()
        for i, preprocessor in enumerate(self.preprocessors):
            preprocessor.learn_one(stage_input)
            if i < len(self.preprocessors) - 1:
                stage_input = preprocessor.transform_one(stage_input)

    def process_data_point(
        self, data: Dict[str, float], topic: str = None, charger_id: str = None
    ) -> AnomalyResult:
        """Process single data point and return anomaly result"""
        start_time = time.time()
        try:
            processed_data = self._transform_pipeline(data)
            score = float(self.model.score_one(processed_data))

            model_ready = self._is_model_ready_for_triggering()
            heuristic_context = self._evaluate_moving_window_heuristic(
                score, model_ready=model_ready
            )
            heuristic_triggered = bool(heuristic_context.get("triggered", False))
            is_anomaly = heuristic_triggered
            severity = self._calculate_heuristic_severity(heuristic_context)
            learn_skipped = False

            # Decision-first flow to avoid contaminating model and baseline.
            if is_anomaly:
                learn_skipped = True
                self.skipped_learning_anomaly_count += 1
            else:
                self.model.learn_one(processed_data)
                # Update preprocessors after scoring so current score is unaffected.
                self._learn_pipeline(data)
                if model_ready:
                    self.score_window.append(score)
            if not model_ready:
                self.pre_ready_suppressed_count += 1

            heuristic_context["learn_skipped"] = learn_skipped
            heuristic_context["reference_count_after"] = len(self.score_window)

            # Update counters
            self.processed_count += 1
            if is_anomaly:
                self.anomaly_count += 1

            # Record processing time
            processing_time = time.time() - start_time
            self.processing_times.append(processing_time)

            # Periodic operations
            if self.processed_count % self.config.checkpoint_interval == 0:
                self._checkpoint_model()

            # Create result
            result = AnomalyResult(
                anomaly_score=score,
                is_anomaly=is_anomaly,
                severity=severity,
                timestamp=datetime.now(timezone.utc),
                model_info=self._get_model_info(),
                raw_data=data,
                processed_features=processed_data,
                topic=topic,
                charger_id=charger_id,
                context={
                    "processing_time_ms": processing_time * 1000,
                    "model_type": self.config.model_type,
                    "score_window": heuristic_context,
                },
            )

            if is_anomaly:
                score_window = result.context.get("score_window", {})
                self.logger.warning(
                    (
                        f"Anomaly detected: score={score:.3f},"
                        f" severity={severity}, topic={topic}, "
                        "trigger=tail_probability"
                    ),
                    extra={
                        "anomaly_score": score,
                        "tail_pvalue": score_window.get("tail_pvalue"),
                        "reference_count": score_window.get("reference_count"),
                        "tail_alpha": score_window.get("tail_alpha"),
                        "model_ready": score_window.get("model_ready"),
                        "learn_skipped": score_window.get("learn_skipped"),
                    },
                )

            return result

        except Exception as e:
            unseen_feature = self._extract_unseen_feature_name(str(e))
            warmup_failure_stage = None
            if unseen_feature is not None:
                try:
                    try:
                        self._learn_pipeline(data)
                    except Exception as preprocess_learn_error:
                        raise RuntimeError(
                            f"preprocessor_learn: {preprocess_learn_error}"
                        ) from preprocess_learn_error

                    try:
                        processed_data = self._transform_pipeline(data)
                    except Exception as transform_error:
                        raise RuntimeError(
                            f"transform_after_warmup: {transform_error}"
                        ) from transform_error

                    try:
                        self.model.learn_one(processed_data)
                    except Exception as model_learn_error:
                        raise RuntimeError(
                            f"model_learn: {model_learn_error}"
                        ) from model_learn_error
                    self.processed_count += 1
                    processing_time = time.time() - start_time
                    self.processing_times.append(processing_time)
                    self.logger.warning(
                        "Primed model with unseen feature '%s'; "
                        "skipping anomaly scoring for this point",
                        unseen_feature,
                    )
                    return AnomalyResult(
                        anomaly_score=0.0,
                        is_anomaly=False,
                        severity="low",
                        timestamp=datetime.now(timezone.utc),
                        model_info=self._get_model_info(),
                        raw_data=data,
                        processed_features=processed_data,
                        topic=topic,
                        charger_id=charger_id,
                        context={
                            "processing_time_ms": processing_time * 1000,
                            "model_type": self.config.model_type,
                            "schema_warmup": True,
                            "unseen_feature": unseen_feature,
                        },
                    )
                except Exception as warmup_error:
                    warmup_failure_stage = self._extract_warmup_failure_stage(
                        str(warmup_error)
                    )
                    self.logger.error(
                        "Model warm-up after unseen-feature error failed "
                        "(stage=%s): %s",
                        warmup_failure_stage or "unknown",
                        warmup_error,
                        exc_info=True,
                    )

            self.logger.error(
                "event=radar.processing_error error=%s", str(e), exc_info=True
            )
            context = {
                "error": str(e),
                "processing_time_ms": (time.time() - start_time) * 1000,
            }
            if unseen_feature is not None:
                context["unseen_feature"] = unseen_feature
            if warmup_failure_stage is not None:
                context["warmup_failure_stage"] = warmup_failure_stage
            return AnomalyResult(
                anomaly_score=0.0,
                is_anomaly=False,
                severity="unknown",
                timestamp=datetime.now(timezone.utc),
                model_info={"error": str(e)},
                raw_data=data,
                topic=topic,
                charger_id=charger_id,
                context=context,
            )

    @staticmethod
    def _extract_unseen_feature_name(error_message: str) -> Optional[str]:
        """Extract unseen feature name from model error message when present."""
        match = _UNSEEN_FEATURE_PATTERN.search(error_message)
        if match:
            return match.group("feature")
        return None

    @staticmethod
    def _extract_warmup_failure_stage(error_message: str) -> Optional[str]:
        """Extract warm-up stage name from prefixed exception message."""
        match = _WARMUP_STAGE_PATTERN.search(error_message)
        if match:
            return match.group("stage")
        return None

    def _calculate_heuristic_severity(self, heuristic_context: Dict[str, Any]) -> str:
        """Calculate severity based on tail probability outlier strength."""
        if not heuristic_context.get("triggered", False):
            return "low"

        tail_pvalue = float(heuristic_context.get("tail_pvalue", 1.0))
        tail_alpha = float(heuristic_context.get("tail_alpha", 0.005))
        if tail_alpha <= 0.0:
            return "medium"

        if tail_pvalue <= tail_alpha / 10.0:
            return "critical"
        if tail_pvalue <= tail_alpha / 4.0:
            return "high"
        return "medium"

    def _evaluate_moving_window_heuristic(
        self, score: float, *, model_ready: bool
    ) -> Dict[str, Any]:
        """Evaluate trailing-reference tail-probability trigger for this service."""
        heuristic_enabled = bool(getattr(self.config, "heuristic_enabled", True))
        min_samples = self._get_heuristic_min_samples()
        tail_alpha = self._get_heuristic_tail_alpha()
        reference_count = len(self.score_window)

        context: Dict[str, Any] = {
            "enabled": heuristic_enabled,
            "window_size": self.score_window.maxlen,
            "reference_count": reference_count,
            "history_count": reference_count,
            "min_samples": min_samples,
            "tail_alpha": tail_alpha,
            "threshold_method": "tail_probability",
            "model_ready": model_ready,
            "triggered": False,
            "warmup": reference_count < min_samples or not model_ready,
            "tail_pvalue": 1.0,
            "learn_skipped": False,
        }

        if not heuristic_enabled:
            return context
        if not model_ready:
            return context
        if reference_count < min_samples or reference_count <= 0:
            return context

        count_ge = sum(1 for existing in self.score_window if existing >= score)
        tail_pvalue = (1.0 + count_ge) / (reference_count + 1.0)
        context["tail_pvalue"] = tail_pvalue
        context["triggered"] = tail_pvalue <= tail_alpha
        context["warmup"] = False
        return context

    def _get_heuristic_window_size(self) -> int:
        """Get moving-window size with safe fallback for legacy config objects."""
        try:
            return max(int(getattr(self.config, "heuristic_window_size", 300)), 3)
        except (TypeError, ValueError):
            return 300

    def _get_heuristic_min_samples(self) -> int:
        """Get minimum sample count with safe fallback and clamping."""
        try:
            min_samples = int(getattr(self.config, "heuristic_min_samples", 30))
        except (TypeError, ValueError):
            min_samples = 30

        min_samples = max(min_samples, 2)
        return min(min_samples, self._get_heuristic_window_size())

    def _get_heuristic_tail_alpha(self) -> float:
        """Get tail-probability threshold with safe fallback."""
        try:
            alpha = float(getattr(self.config, "heuristic_tail_alpha", 0.005))
        except (TypeError, ValueError):
            alpha = 0.005
        if alpha <= 0.0 or alpha >= 1.0:
            return 0.005
        return alpha

    def _is_model_ready_for_triggering(self) -> bool:
        """Return whether model output is ready for anomaly triggering semantics."""
        if str(getattr(self.config, "model_type", "")).lower() != "knn":
            return True
        engine = getattr(self.model, "engine", None)
        if engine is None:
            return True
        # engine.warm_upengine.window introduced in river 0.21 (KNNAnomalyDetector)
        try:
            warm_up = int(getattr(engine, "warm_up", 0))
        except (TypeError, ValueError):
            warm_up = 0
        if warm_up <= 0:
            return True
        try:
            current_size = len(getattr(engine, "window", []))
        except TypeError:
            current_size = 0
        return current_size >= warm_up

    def _checkpoint_model(self):
        """Save model and preprocessor checkpoint with HMAC signature.

        Checkpoints are namespaced by SERVICE_ID to support multiple RADAR
        containers running independently. If RADAR_CHECKPOINT_SECRET is set,
        the checkpoint is signed with HMAC-SHA256.
        """
        try:
            checkpoint_settings = get_radar_checkpoint_settings()
            checkpoint_dir = checkpoint_settings.RADAR_CHECKPOINT_DIR
            service_id = checkpoint_settings.SERVICE_ID
            os.makedirs(checkpoint_dir, exist_ok=True)

            timestamp = int(time.time())
            checkpoint_name = f"{service_id}_{self.processed_count}_{timestamp}.pkl"
            checkpoint_path = f"{checkpoint_dir}/{checkpoint_name}"

            # Serialize checkpoint data
            checkpoint_data = pickle.dumps(
                {
                    "model": self.model,
                    "preprocessors": self.preprocessors,
                    "processed_count": self.processed_count,
                    "anomaly_count": self.anomaly_count,
                    "score_window": list(self.score_window),
                    "skipped_learning_anomaly_count": (
                        self.skipped_learning_anomaly_count
                    ),
                    "pre_ready_suppressed_count": self.pre_ready_suppressed_count,
                    "config": self.config,
                    "service_id": service_id,
                    "schema_signature": self.schema_signature,
                }
            )

            # Write checkpoint file
            with open(checkpoint_path, "wb") as f:
                f.write(checkpoint_data)

            # Write signature file if secret is configured
            signature = _sign_checkpoint_data(checkpoint_data)
            if signature:
                sig_path = checkpoint_path + ".sig"
                with open(sig_path, "w") as f:
                    f.write(signature)
                self.logger.info(f"Checkpoint saved with signature: {checkpoint_path}")
            else:
                self.logger.info(f"Checkpoint saved (unsigned): {checkpoint_path}")

        except Exception as e:
            self.logger.error(
                "event=radar.checkpoint_save_failed error=%s",
                str(e),
                exc_info=True,
            )

    def _get_model_info(self) -> Dict[str, Any]:
        """Get model state information"""
        return {
            "strategy": "adaptive_stream",
            "processed_count": self.processed_count,
            "anomaly_count": self.anomaly_count,
            "anomaly_rate": self.anomaly_count / max(self.processed_count, 1),
            "reference_count": len(self.score_window),
            "min_samples": self._get_heuristic_min_samples(),
            "skipped_learning_anomaly_count": self.skipped_learning_anomaly_count,
            "pre_ready_suppressed_count": self.pre_ready_suppressed_count,
            "memory_usage_mb": self._get_memory_usage(),
            "avg_processing_time_ms": sum(self.processing_times)
            / max(len(self.processing_times), 1)
            * 1000,
            "uptime_seconds": time.time() - self.start_time,
        }

    def _get_memory_usage(self) -> float:
        """Get current memory usage in MB"""
        try:
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / 1024 / 1024
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return 0.0


class StaticConformalState(Enum):
    """Lifecycle states for static conformal monitoring."""

    COLLECTING = "collecting"
    CALIBRATING = "calibrating"
    TRAINING = "training"
    READY = "ready"
    FAILED = "failed"


class RestartedMartingaleAlarmController:
    """Power martingale alarm with alpha-spent resets."""

    def __init__(
        self,
        *,
        alpha: float,
        epsilon: float,
        alarm_count: int = 0,
        tested_count: int = 0,
        martingale: Any = None,
    ):
        self.method = "power"
        self.alpha = float(alpha)
        self.epsilon = float(epsilon)
        self.alarm_count = int(alarm_count)
        self.tested_count = int(tested_count)
        self._martingale = martingale or self._new_martingale()

    @classmethod
    def from_config(cls, config: Any) -> "RestartedMartingaleAlarmController":
        return cls(alpha=config.alpha, epsilon=config.epsilon)

    @property
    def num_test(self) -> int:
        return self.tested_count

    @property
    def episode_alpha(self) -> float:
        return self.alpha / (2.0 ** (self.alarm_count + 1))

    @property
    def restarted_ville_threshold(self) -> float:
        return 1.0 / self.episode_alpha

    def _new_martingale(self) -> Any:
        from nonconform.martingales import AlarmConfig, PowerMartingale

        return PowerMartingale(
            epsilon=self.epsilon,
            alarm_config=AlarmConfig(
                restarted_ville_threshold=self.restarted_ville_threshold
            ),
        )

    def update(self, p_value: float) -> Dict[str, Any]:
        state = self._martingale.update(p_value)
        self.tested_count += 1
        alarm_fired = "restarted_ville" in state.triggered_alarms
        context = {
            "martingale_method": self.method,
            "epsilon": self.epsilon,
            "alpha": self.alpha,
            "episode_alpha": self.episode_alpha,
            "restarted_ville_threshold": self.restarted_ville_threshold,
            "restarted_martingale": float(state.restarted_martingale),
            "alarm_fired": alarm_fired,
            "alarm_count": self.alarm_count,
            "tested_count": self.tested_count,
        }
        if alarm_fired:
            self.alarm_count += 1
            self._martingale = self._new_martingale()
            context["alarm_count"] = self.alarm_count
        return context


class StaticConformalDetectionService:
    """Train-once static baseline detector using conformal p-values and martingales."""

    def __init__(
        self,
        config: AnomalyDetectionConfig,
        checkpoint: Optional[Dict[str, Any]] = None,
    ):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.schema_signature = self._build_schema_signature_from_config(config)
        self.static_config = config.static_baseline_config
        self.start_time = time.time()
        self.processing_times: deque = deque(maxlen=1000)
        self._training_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self._training_future: Optional[concurrent.futures.Future] = None
        self.training_error: Optional[str] = None

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
        self.training_buffer: list[Dict[str, float]] = []
        self.calibration_buffer: list[Dict[str, float]] = []
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

    def _restore_from_checkpoint(self, checkpoint: Dict[str, Any]) -> None:
        self.state = StaticConformalState(
            checkpoint.get("static_state", StaticConformalState.COLLECTING.value)
        )
        self.training_buffer = list(checkpoint.get("training_buffer", []))
        self.calibration_buffer = list(checkpoint.get("calibration_buffer", []))
        self.feature_keys = list(checkpoint.get("feature_keys", []))
        self.conformal_detector = checkpoint.get("conformal_detector")
        self.alarm_controller = checkpoint.get("alarm_controller")
        if self.alarm_controller is None:
            legacy_fdr_controller = checkpoint.get("fdr_controller")
            self.alarm_controller = self._create_alarm_controller(
                alarm_count=int(checkpoint.get("alarm_count", 0)),
                tested_count=int(
                    checkpoint.get(
                        "tested_count",
                        getattr(legacy_fdr_controller, "num_test", 0),
                    )
                ),
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
        checkpoint = AnomalyDetectionService._load_and_verify_checkpoint(
            checkpoint_path
        )

        saved_strategy = checkpoint.get("strategy")
        if saved_strategy != "static_baseline":
            raise ValueError(
                "Checkpoint strategy does not match static_baseline configuration."
            )

        saved_schema_signature = checkpoint.get("schema_signature")
        current_schema_signature = cls._build_schema_signature_from_config(config)
        accepted_signatures = {current_schema_signature}
        if "fdr_controller" in checkpoint:
            accepted_signatures.add(
                cls._build_legacy_fdr_schema_signature_from_config(config)
            )
        if (
            not saved_schema_signature
            or saved_schema_signature not in accepted_signatures
        ):
            raise ValueError(
                "Checkpoint schema signature does not match current static "
                "configuration. Starting fresh is required."
            )

        return cls(config, checkpoint=checkpoint)

    @classmethod
    def _build_schema_signature_from_config(cls, config: Any) -> str:
        static_config = getattr(config, "static_baseline_config", None)
        if static_config is not None and hasattr(static_config, "model_dump"):
            static_payload = static_config.model_dump(
                exclude={"calibration_fraction", "fdr_config"},
                exclude_none=True,
            )
        else:
            static_payload = {}
        return cls._build_static_schema_signature(config, static_payload)

    @classmethod
    def _build_legacy_fdr_schema_signature_from_config(cls, config: Any) -> str:
        static_config = getattr(config, "static_baseline_config", None)
        if static_config is not None and hasattr(static_config, "model_dump"):
            static_payload = static_config.model_dump(
                exclude={"calibration_window_size", "martingale_config"},
                exclude_none=True,
            )
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
        self, data: Dict[str, float], topic: str = None, charger_id: str = None
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
        data: Dict[str, float],
        topic: Optional[str],
        charger_id: Optional[str],
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
        data: Dict[str, float],
        topic: Optional[str],
        charger_id: Optional[str],
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
        data: Dict[str, float],
        topic: Optional[str],
        charger_id: Optional[str],
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
        data: Dict[str, float],
        topic: Optional[str],
        charger_id: Optional[str],
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
            float(alarm_context["episode_alpha"]),
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
                "restarted_martingale=%.6f severity=%s topic=%s",
                p_value,
                float(alarm_context["restarted_martingale"]),
                severity,
                topic,
                extra={
                    "conformal_pvalue": p_value,
                    "martingale_method": alarm_context["martingale_method"],
                    "episode_alpha": alarm_context["episode_alpha"],
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
        data: Dict[str, float],
        topic: Optional[str],
        charger_id: Optional[str],
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

    def _validate_or_freeze_feature_schema(
        self, data: Dict[str, float]
    ) -> Optional[str]:
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

    def _vectorize(self, data: Dict[str, float]) -> List[float]:
        return [float(data[key]) for key in self.feature_keys]

    def _fit_static_baseline(
        self,
        training_samples: list[Dict[str, float]],
        calibration_samples: list[Dict[str, float]],
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

    def _create_alarm_controller(
        self, *, alarm_count: int = 0, tested_count: int = 0
    ) -> RestartedMartingaleAlarmController:
        martingale_config = self.static_config.martingale_config
        return RestartedMartingaleAlarmController(
            alpha=martingale_config.alpha,
            epsilon=martingale_config.epsilon,
            alarm_count=alarm_count,
            tested_count=tested_count,
        )

    def _create_pyod_detector(self) -> Any:
        model_type = self.static_config.model_type
        params = dict(self.static_config.model_params or {})
        if self.static_config.seed is not None:
            params.setdefault("random_state", self.static_config.seed)

        return self._instantiate_pyod_detector(model_type, params)

    def _instantiate_pyod_detector(
        self, model_type: str, params: Dict[str, Any]
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

    def _compute_p_value(self, vector: List[float]) -> float:
        p_values = self.conformal_detector.compute_p_values(
            np.asarray([vector], dtype=float)
        )
        p_value = float(p_values[0])
        if p_value < 0.0:
            return 0.0
        if p_value > 1.0:
            return 1.0
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
        data: Dict[str, float],
        processed_features: Optional[Dict[str, float]],
        score: float,
        is_anomaly: bool,
        severity: str,
        topic: Optional[str],
        charger_id: Optional[str],
        start_time: float,
        phase: str,
        extra_context: Optional[Dict[str, Any]] = None,
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
            timestamp=datetime.now(timezone.utc),
            model_info=self._get_model_info(),
            raw_data=data,
            processed_features=processed_features,
            topic=topic,
            charger_id=charger_id,
            context=context,
        )

    def _checkpoint_model(self) -> None:
        try:
            checkpoint_settings = get_radar_checkpoint_settings()
            checkpoint_dir = checkpoint_settings.RADAR_CHECKPOINT_DIR
            service_id = checkpoint_settings.SERVICE_ID
            os.makedirs(checkpoint_dir, exist_ok=True)

            timestamp = int(time.time())
            checkpoint_name = f"{service_id}_{self.processed_count}_{timestamp}.pkl"
            checkpoint_path = f"{checkpoint_dir}/{checkpoint_name}"
            checkpoint_data = pickle.dumps(
                {
                    "strategy": "static_baseline",
                    "static_state": self.state.value,
                    "training_buffer": self.training_buffer,
                    "calibration_buffer": self.calibration_buffer,
                    "feature_keys": self.feature_keys,
                    "conformal_detector": self.conformal_detector,
                    "alarm_controller": self.alarm_controller,
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
            )

            with open(checkpoint_path, "wb") as f:
                f.write(checkpoint_data)

            signature = _sign_checkpoint_data(checkpoint_data)
            if signature:
                with open(checkpoint_path + ".sig", "w") as f:
                    f.write(signature)
                self.logger.info(
                    "Static conformal checkpoint saved with signature: %s",
                    checkpoint_path,
                )
            else:
                self.logger.info(
                    "Static conformal checkpoint saved (unsigned): %s",
                    checkpoint_path,
                )
        except Exception as exc:
            self.logger.error(
                "event=radar.static_conformal_checkpoint_save_failed error=%s",
                str(exc),
                exc_info=True,
            )

    def _get_model_info(self) -> Dict[str, Any]:
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


class ResilientAnomalyDetector:
    """
    Resilient anomaly detector with error handling and fallback mechanisms
    Implements circuit breaker pattern from guide.md
    """

    def __init__(
        self,
        primary_service: AnomalyDetectionService,
        fallback_service: Optional[AnomalyDetectionService] = None,
    ):
        self.primary_service = primary_service
        self.fallback_service = fallback_service
        self.state = ServiceState.HEALTHY

        # Error tracking
        self.error_count = 0
        self.error_window = 100
        self.error_threshold = 0.1  # 10% error rate
        self.last_errors = deque(maxlen=self.error_window)

        # Circuit breaker
        self.circuit_breaker_open = False
        self.circuit_breaker_timeout = 300  # 5 minutes
        self.circuit_breaker_opened_at = None

        self.logger = logging.getLogger(__name__)

    async def stop(self) -> None:
        """Release resources held by wrapped detector services."""
        for service in (self.primary_service, self.fallback_service):
            shutdown = getattr(service, "shutdown", None)
            if callable(shutdown):
                shutdown()

    def process_with_resilience(
        self, data: Dict[str, float], topic: str = None, charger_id: str = None
    ) -> AnomalyResult:
        """Process data point with error handling and fallback"""
        try:
            # Check circuit breaker
            if self._should_use_circuit_breaker():
                return self._fallback_processing(
                    data, topic, charger_id, "circuit_breaker"
                )

            # Try primary service
            result = self.primary_service.process_data_point(data, topic, charger_id)
            self._record_success()

            return result

        except Exception as e:
            self._record_error(e)

            # Try fallback processing
            return self._fallback_processing(data, topic, charger_id, str(e))

    def _fallback_processing(
        self, data: Dict[str, float], topic: str, charger_id: str, reason: str
    ) -> AnomalyResult:
        """Fallback processing when primary fails"""
        self.logger.warning("event=radar.fallback_processing reason=%s", reason)

        try:
            if self.fallback_service:
                result = self.fallback_service.process_data_point(
                    data, topic, charger_id
                )
                result.context = result.context or {}
                result.context["fallback_reason"] = reason
                result.context["model_used"] = "fallback"
                return result
            # Simple statistical fallback
            score = self._simple_statistical_anomaly_score(data)
            if not hasattr(self.primary_service, "_evaluate_moving_window_heuristic"):
                return AnomalyResult(
                    anomaly_score=score,
                    is_anomaly=False,
                    severity="unknown",
                    timestamp=datetime.now(timezone.utc),
                    model_info={"model_used": "statistical"},
                    raw_data=data,
                    topic=topic,
                    charger_id=charger_id,
                    context={
                        "fallback_reason": reason,
                        "model_used": "statistical",
                        "service_state": ServiceState.DEGRADED.value,
                    },
                )

            heuristic_context = self.primary_service._evaluate_moving_window_heuristic(
                score, model_ready=True
            )
            if not heuristic_context.get("triggered", False) and bool(
                heuristic_context.get("model_ready", True)
            ):
                self.primary_service.score_window.append(score)
                heuristic_context["reference_count_after"] = len(
                    self.primary_service.score_window
                )
            return AnomalyResult(
                anomaly_score=score,
                is_anomaly=bool(heuristic_context.get("triggered", False)),
                severity=self.primary_service._calculate_heuristic_severity(
                    heuristic_context
                ),
                timestamp=datetime.now(timezone.utc),
                model_info={"model_used": "statistical"},
                raw_data=data,
                topic=topic,
                charger_id=charger_id,
                context={
                    "fallback_reason": reason,
                    "model_used": "statistical",
                    "service_state": ServiceState.DEGRADED.value,
                    "score_window": heuristic_context,
                },
            )

        except Exception as e:
            self.logger.error(
                "event=radar.fallback_processing_failed error=%s",
                str(e),
                exc_info=True,
            )
            return AnomalyResult(
                anomaly_score=0.0,
                is_anomaly=False,
                severity="unknown",
                timestamp=datetime.now(),
                model_info={"error": str(e), "model_used": "none"},
                raw_data=data,
                topic=topic,
                charger_id=charger_id,
                context={
                    "error": str(e),
                    "fallback_reason": reason,
                    "service_state": ServiceState.FAILED.value,
                },
            )

    def _simple_statistical_anomaly_score(self, data: Dict[str, float]) -> float:
        """Simple statistical anomaly detection as last resort"""
        try:
            values = list(data.values())
            if not hasattr(self, "_running_mean"):
                self._running_mean = np.mean(values)
                self._running_std = 1.0
                self._count = 1
                return 0.0

            # Update running statistics
            current_mean = np.mean(values)
            self._count += 1
            alpha = 1.0 / min(self._count, 100)  # Cap the learning rate
            self._running_mean = (1 - alpha) * self._running_mean + alpha * current_mean

            # Calculate anomaly score based on deviation
            deviation = abs(current_mean - self._running_mean)
            return min(deviation / (self._running_std + 1e-8), 1.0)

        except (ImportError, ValueError, TypeError, ZeroDivisionError):
            return 0.0

    def _record_error(self, error: Exception):
        """Record error for circuit breaker logic"""
        self.error_count += 1
        self.last_errors.append(time.time())

        # Check if we should open circuit breaker
        recent_error_rate = len(self.last_errors) / self.error_window
        if recent_error_rate > self.error_threshold:
            self._open_circuit_breaker()

        self.logger.error("event=radar.model_error error=%s", error)

    def _record_success(self):
        """Record successful processing"""
        if self.circuit_breaker_open:
            # Try to close circuit breaker
            self._close_circuit_breaker()

    def _should_use_circuit_breaker(self) -> bool:
        """Check if circuit breaker should prevent primary model use"""
        if not self.circuit_breaker_open:
            return False

        # Check if timeout has passed
        if (
            time.time() - self.circuit_breaker_opened_at
        ) > self.circuit_breaker_timeout:
            self._close_circuit_breaker()
            return False

        return True

    def _open_circuit_breaker(self):
        """Open circuit breaker"""
        self.circuit_breaker_open = True
        self.circuit_breaker_opened_at = time.time()
        self.state = ServiceState.DEGRADED
        self.logger.warning("Circuit breaker opened - using fallback processing")

    def _close_circuit_breaker(self):
        """Close circuit breaker"""
        self.circuit_breaker_open = False
        self.circuit_breaker_opened_at = None
        self.state = ServiceState.HEALTHY
        self.logger.info("Circuit breaker closed - resuming normal processing")

    def get_service_state(self) -> ServiceState:
        """Get current service state"""
        return self.state

    def get_health_info(self) -> Dict[str, Any]:
        """Get health information"""
        return {
            "state": self.state.value,
            "circuit_breaker_open": self.circuit_breaker_open,
            "error_count": self.error_count,
            "recent_error_rate": len(self.last_errors) / self.error_window,
            "primary_service_stats": self.primary_service._get_model_info(),
            "uptime_seconds": time.time() - getattr(self, "start_time", time.time()),
        }


class MemoryManager:
    """Memory management utilities following guide.md patterns"""

    def __init__(self, max_memory_mb=2000, cleanup_threshold=0.8):
        self.max_memory_mb = max_memory_mb
        self.cleanup_threshold = cleanup_threshold
        self.process = psutil.Process(os.getpid())
        self.logger = logging.getLogger(__name__)

    def get_memory_usage(self) -> float:
        """Get current memory usage in MB"""
        return self.process.memory_info().rss / 1024 / 1024

    def should_cleanup(self) -> bool:
        """Check if memory cleanup is needed"""
        current_memory = self.get_memory_usage()
        return current_memory > (self.max_memory_mb * self.cleanup_threshold)

    def force_cleanup(self) -> float:
        """Force garbage collection and memory cleanup"""
        before_memory = self.get_memory_usage()

        # Run garbage collection
        collected = gc.collect()

        after_memory = self.get_memory_usage()
        freed_memory = before_memory - after_memory

        self.logger.debug(
            "event=radar.memory_cleanup freed_mb=%.1f collected=%s",
            freed_memory,
            collected,
        )

        return freed_memory


class SecurityValidator:
    """Input validation and sanitization following guide.md patterns"""

    def __init__(
        self,
        max_feature_count=100,
        max_string_length=1000,
        metadata_feature_keys: Optional[set[str]] = None,
    ):
        self.max_feature_count = max_feature_count
        self.max_string_length = max_string_length
        keys = metadata_feature_keys or set(_DEFAULT_METADATA_FEATURE_KEYS)
        self.metadata_feature_keys = {key.lower() for key in keys}
        self.logger = logging.getLogger(__name__)

    def validate_and_sanitize(self, data: Dict[str, Any]) -> Dict[str, float]:
        """Validate and sanitize input data to numeric format"""
        if not isinstance(data, dict):
            raise ValueError("Input must be a dictionary")

        if len(data) > self.max_feature_count:
            raise ValueError(
                f"Too many features: {len(data)} > {self.max_feature_count}"
            )

        sanitized = {}

        for key, value in data.items():
            # Validate key
            if not isinstance(key, str) or len(key) > 100:
                continue  # Skip invalid keys
            if key.lower() in self.metadata_feature_keys:
                continue

            # Convert value to float
            try:
                if isinstance(value, (int, float)):
                    if -1e10 < value < 1e10:  # Reasonable range
                        sanitized[key] = float(value)
                elif isinstance(value, str):
                    if len(value) > self.max_string_length:
                        continue  # Skip overly long strings

                    # Try to convert to float
                    try:
                        sanitized[key] = float(value)
                    except ValueError:
                        # Hash string to numeric value
                        hash_val = int(hashlib.md5(value.encode()).hexdigest()[:8], 16)
                        sanitized[key] = float(hash_val % 10000)
                elif isinstance(value, bool):
                    sanitized[key] = float(value)
            except Exception as e:
                self.logger.debug(f"Skipping invalid feature {key}: {e}")
                continue

        return sanitized
