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
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from collections import deque
from enum import Enum

# Model registry for dynamic model loading
from off_key_core.models import (
    create_model_instance,
    validate_preprocessing_steps,
    get_preprocessor_class,
)

from .config import AnomalyDetectionConfig
from .models import AnomalyResult


# =============================================================================
# Checkpoint Security
# =============================================================================

_checkpoint_secret_warning_logged = False


def _get_checkpoint_secret() -> bytes:
    """Get checkpoint signing secret from environment."""
    return os.getenv("RADAR_CHECKPOINT_SECRET", "").encode()


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

    def _restore_from_checkpoint(self, checkpoint: Dict[str, Any]):
        """Restore state from checkpoint data."""
        self.model = checkpoint["model"]
        self.preprocessors = checkpoint.get("preprocessors", [])
        self.processed_count = checkpoint["processed_count"]
        self.anomaly_count = checkpoint["anomaly_count"]
        self.last_checkpoint = self.processed_count

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
        checkpoint = pickle.loads(raw_data)
        return checkpoint

    @classmethod
    def from_checkpoint(
        cls, checkpoint_path: str, config: AnomalyDetectionConfig
    ) -> "AnomalyDetectionService":
        """Restore service from a checkpoint file.

        This restores the learned state of both the model and preprocessors,
        allowing the service to resume from where it left off.

        Args:
            checkpoint_path: Path to the pickle checkpoint file
            config: Current configuration (used for thresholds, etc.)

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
        if saved_config and hasattr(saved_config, "model_type"):
            if saved_config.model_type != config.model_type:
                raise ValueError(
                    f"Checkpoint model type '{saved_config.model_type}' "
                    f"does not match config model type '{config.model_type}'."
                )

        logger.info(f"Loading verified checkpoint: {checkpoint_path}")
        return cls(config, checkpoint=checkpoint)

    def _create_model(self):
        """Factory method for model creation using registry.

        Uses create_model_instance which handles special cases like KNN
        that require additional setup (e.g., similarity engine).
        """
        try:
            # Log params before validation
            self.logger.info(
                f"Creating model '{self.config.model_type}'"
                f" with params: {self.config.model_params}"
            )

            # Use create_model_instance which handles special cases like KNN
            return create_model_instance(
                self.config.model_type, self.config.model_params
            )

        except ImportError as e:
            self.logger.error(f"Failed to import model: {e}")
            raise
        except ValueError as e:
            self.logger.error(f"Invalid model configuration: {e}")
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
                self.logger.info(f"Enabled preprocessing pipeline: {step_types}")
        except Exception as e:
            self.logger.error(f"Failed to create preprocessing pipeline: {e}")
            raise

        return preprocessors

    def process_data_point(
        self, data: Dict[str, float], topic: str = None, charger_id: str = None
    ) -> AnomalyResult:
        """Process single data point and return anomaly result"""
        start_time = time.time()

        try:
            processed_data = data.copy()
            # Apply preprocessing using the state learned so far (no leakage)
            for preprocessor in self.preprocessors:
                processed_data = preprocessor.transform_one(processed_data)

            # Anomaly detection: score first, then learn
            score = self.model.score_one(processed_data)
            self.model.learn_one(processed_data)

            # Update preprocessors after scoring to avoid influencing current result
            for preprocessor in self.preprocessors:
                preprocessor.learn_one(data)

            # Thresholding
            is_anomaly = score > self.config.thresholds.get("medium", 0.6)
            severity = self._calculate_severity(score)

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
                },
            )

            if is_anomaly:
                self.logger.warning(
                    f"Anomaly detected: score={score:.3f},"
                    f" severity={severity}, topic={topic}"
                )

            return result

        except Exception as e:
            self.logger.error(f"Processing error: {e}")
            return AnomalyResult(
                anomaly_score=0.0,
                is_anomaly=False,
                severity="unknown",
                timestamp=datetime.now(timezone.utc),
                model_info={"error": str(e)},
                raw_data=data,
                topic=topic,
                charger_id=charger_id,
                context={
                    "error": str(e),
                    "processing_time_ms": (time.time() - start_time) * 1000,
                },
            )

    def _calculate_severity(self, score: float) -> str:
        """Calculate anomaly severity level"""
        thresholds = self.config.thresholds

        if score > thresholds.get("critical", 0.9):
            return "critical"
        elif score > thresholds.get("high", 0.8):
            return "high"
        elif score > thresholds.get("medium", 0.6):
            return "medium"
        else:
            return "low"

    def _checkpoint_model(self):
        """Save model and preprocessor checkpoint with HMAC signature.

        Checkpoints are namespaced by SERVICE_ID to support multiple RADAR
        containers running independently. If RADAR_CHECKPOINT_SECRET is set,
        the checkpoint is signed with HMAC-SHA256.
        """
        try:
            checkpoint_dir = os.getenv("RADAR_CHECKPOINT_DIR", "checkpoints")
            service_id = os.getenv("SERVICE_ID", "default")
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
                    "config": self.config,
                    "service_id": service_id,
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
            self.logger.error(f"Failed to save checkpoint: {e}")

    def _get_model_info(self) -> Dict[str, Any]:
        """Get model state information"""
        return {
            "processed_count": self.processed_count,
            "anomaly_count": self.anomaly_count,
            "anomaly_rate": self.anomaly_count / max(self.processed_count, 1),
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
        self.logger.warning(f"Using fallback processing: {reason}")

        try:
            if self.fallback_service:
                result = self.fallback_service.process_data_point(
                    data, topic, charger_id
                )
                result.context = result.context or {}
                result.context["fallback_reason"] = reason
                result.context["model_used"] = "fallback"
                return result
            else:
                # Simple statistical fallback
                score = self._simple_statistical_anomaly_score(data)
                return AnomalyResult(
                    anomaly_score=score,
                    is_anomaly=score > 0.7,
                    severity="medium" if score > 0.7 else "low",
                    timestamp=datetime.now(),
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

        except Exception as e:
            self.logger.error(f"Fallback processing failed: {e}")
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
            import numpy as np

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
            score = min(deviation / (self._running_std + 1e-8), 1.0)
            return score

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

        self.logger.error(f"Model error: {error}")

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

        self.logger.info(
            f"Memory cleanup: freed {freed_memory:.1f} MB,"
            f" collected {collected} objects"
        )

        return freed_memory


class SecurityValidator:
    """Input validation and sanitization following guide.md patterns"""

    def __init__(self, max_feature_count=100, max_string_length=1000):
        self.max_feature_count = max_feature_count
        self.max_string_length = max_string_length
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
