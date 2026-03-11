"""
Tests for AnomalyDetectionService and related components.

Tests cover:
- Data point processing
- Severity calculation
- Preprocessing pipeline
- Error handling
- Resilient detector with circuit breaker
- Security validation
- Memory management
"""

import pytest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace


class TestAnomalyDetectionService:
    """Tests for AnomalyDetectionService core functionality."""

    def test_process_data_point_normal(self, anomaly_config, sample_telemetry_data):
        """Test processing a normal (non-anomalous) data point."""
        from off_key_mqtt_radar.detector import AnomalyDetectionService

        # Mock model to return low score
        with patch.object(AnomalyDetectionService, "_create_model") as mock_create:
            mock_model = MagicMock()
            mock_model.score_one.return_value = 0.3
            mock_model.learn_one = MagicMock()
            mock_create.return_value = mock_model

            with patch.object(
                AnomalyDetectionService, "_create_preprocessors", return_value=[]
            ):
                service = AnomalyDetectionService(anomaly_config)
                result = service.process_data_point(
                    sample_telemetry_data, topic="test/topic", charger_id="charger-001"
                )

        assert result.is_anomaly is False
        assert result.severity == "low"
        assert result.anomaly_score == 0.3
        assert service.processed_count == 1
        assert service.anomaly_count == 0

    def test_process_data_point_anomaly(self, anomaly_config, sample_telemetry_data):
        """Test processing an anomalous data point via moving-window heuristic."""
        from off_key_mqtt_radar.detector import AnomalyDetectionService

        anomaly_config.heuristic_enabled = True
        anomaly_config.heuristic_window_size = 10
        anomaly_config.heuristic_min_samples = 3
        anomaly_config.heuristic_zscore_threshold = 3.0

        with patch.object(AnomalyDetectionService, "_create_model") as mock_create:
            mock_model = MagicMock()
            mock_model.score_one.side_effect = [0.10, 0.12, 0.11, 0.85]
            mock_model.learn_one = MagicMock()
            mock_create.return_value = mock_model

            with patch.object(
                AnomalyDetectionService, "_create_preprocessors", return_value=[]
            ):
                service = AnomalyDetectionService(anomaly_config)
                service.process_data_point(
                    sample_telemetry_data, topic="test/topic", charger_id="charger-001"
                )
                service.process_data_point(
                    sample_telemetry_data, topic="test/topic", charger_id="charger-001"
                )
                service.process_data_point(
                    sample_telemetry_data, topic="test/topic", charger_id="charger-001"
                )
                result = service.process_data_point(
                    sample_telemetry_data, topic="test/topic", charger_id="charger-001"
                )

        assert result.is_anomaly is True
        assert result.severity == "critical"
        assert result.anomaly_score == 0.85
        assert service.anomaly_count == 1

    def test_process_data_point_triggers_moving_window_heuristic(self, anomaly_config):
        """Trigger anomaly when score is a z-score outlier in the service window."""
        from off_key_mqtt_radar.detector import AnomalyDetectionService

        anomaly_config.thresholds = {"medium": 0.6, "high": 0.8, "critical": 0.9}
        anomaly_config.heuristic_enabled = True
        anomaly_config.heuristic_window_size = 10
        anomaly_config.heuristic_min_samples = 3
        anomaly_config.heuristic_zscore_threshold = 3.0

        with patch.object(AnomalyDetectionService, "_create_model") as mock_create:
            mock_model = MagicMock()
            mock_model.score_one.side_effect = [0.10, 0.12, 0.11, 0.35]
            mock_model.learn_one = MagicMock()
            mock_create.return_value = mock_model

            with patch.object(
                AnomalyDetectionService, "_create_preprocessors", return_value=[]
            ):
                service = AnomalyDetectionService(anomaly_config)
                first = service.process_data_point({"x": 1.0})
                second = service.process_data_point({"x": 1.1})
                third = service.process_data_point({"x": 0.9})
                fourth = service.process_data_point({"x": 5.0})

        assert first.is_anomaly is False
        assert second.is_anomaly is False
        assert third.is_anomaly is False
        assert fourth.is_anomaly is True
        assert fourth.severity == "medium"
        assert fourth.context["score_window"]["triggered"] is True

    def test_process_data_point_does_not_use_moving_window_when_disabled(
        self, anomaly_config
    ):
        """Do not trigger moving-window anomaly if heuristic is disabled."""
        from off_key_mqtt_radar.detector import AnomalyDetectionService

        anomaly_config.thresholds = {"medium": 0.6, "high": 0.8, "critical": 0.9}
        anomaly_config.heuristic_enabled = False

        with patch.object(AnomalyDetectionService, "_create_model") as mock_create:
            mock_model = MagicMock()
            mock_model.score_one.side_effect = [0.10, 0.12, 0.11, 0.35]
            mock_model.learn_one = MagicMock()
            mock_create.return_value = mock_model

            with patch.object(
                AnomalyDetectionService, "_create_preprocessors", return_value=[]
            ):
                service = AnomalyDetectionService(anomaly_config)
                service.process_data_point({"x": 1.0})
                service.process_data_point({"x": 1.1})
                service.process_data_point({"x": 0.9})
                fourth = service.process_data_point({"x": 5.0})

        assert fourth.is_anomaly is False
        assert fourth.context["score_window"]["enabled"] is False

    def test_calculate_severity_low(self, anomaly_config):
        """Test severity calculation for low score."""
        from off_key_mqtt_radar.detector import AnomalyDetectionService

        with patch.object(AnomalyDetectionService, "_create_model"):
            with patch.object(
                AnomalyDetectionService, "_create_preprocessors", return_value=[]
            ):
                service = AnomalyDetectionService(anomaly_config)
                severity = service._calculate_heuristic_severity(
                    {"triggered": False, "zscore": 0.0, "zscore_threshold": 3.0}
                )

        assert severity == "low"

    def test_calculate_severity_medium(self, anomaly_config):
        """Test severity calculation for medium score."""
        from off_key_mqtt_radar.detector import AnomalyDetectionService

        with patch.object(AnomalyDetectionService, "_create_model"):
            with patch.object(
                AnomalyDetectionService, "_create_preprocessors", return_value=[]
            ):
                service = AnomalyDetectionService(anomaly_config)
                severity = service._calculate_heuristic_severity(
                    {"triggered": True, "zscore": 3.0, "zscore_threshold": 3.0}
                )

        assert severity == "medium"

    def test_calculate_severity_high(self, anomaly_config):
        """Test severity calculation for high score."""
        from off_key_mqtt_radar.detector import AnomalyDetectionService

        with patch.object(AnomalyDetectionService, "_create_model"):
            with patch.object(
                AnomalyDetectionService, "_create_preprocessors", return_value=[]
            ):
                service = AnomalyDetectionService(anomaly_config)
                severity = service._calculate_heuristic_severity(
                    {"triggered": True, "zscore": 5.5, "zscore_threshold": 3.0}
                )

        assert severity == "high"

    def test_calculate_severity_critical(self, anomaly_config):
        """Test severity calculation for critical score."""
        from off_key_mqtt_radar.detector import AnomalyDetectionService

        with patch.object(AnomalyDetectionService, "_create_model"):
            with patch.object(
                AnomalyDetectionService, "_create_preprocessors", return_value=[]
            ):
                service = AnomalyDetectionService(anomaly_config)
                severity = service._calculate_heuristic_severity(
                    {"triggered": True, "zscore": 8.0, "zscore_threshold": 3.0}
                )

        assert severity == "critical"

    def test_process_with_preprocessing(self, anomaly_config, sample_telemetry_data):
        """Test that preprocessing is applied correctly."""
        from off_key_mqtt_radar.detector import AnomalyDetectionService

        mock_preprocessor = MagicMock()
        mock_preprocessor.transform_one = MagicMock(
            side_effect=lambda x: {k: v * 2 for k, v in x.items()}
        )
        mock_preprocessor.learn_one = MagicMock()

        with patch.object(AnomalyDetectionService, "_create_model") as mock_create:
            mock_model = MagicMock()
            mock_model.score_one.return_value = 0.5
            mock_model.learn_one = MagicMock()
            mock_create.return_value = mock_model

            with patch.object(
                AnomalyDetectionService,
                "_create_preprocessors",
                return_value=[mock_preprocessor],
            ):
                service = AnomalyDetectionService(anomaly_config)
                service.process_data_point(sample_telemetry_data)

        # Verify preprocessor was called
        mock_preprocessor.transform_one.assert_called_once()
        mock_preprocessor.learn_one.assert_called_once()

    def test_process_error_returns_safe_result(
        self, anomaly_config, sample_telemetry_data
    ):
        """Test that errors during processing return a safe result."""
        from off_key_mqtt_radar.detector import AnomalyDetectionService

        with patch.object(AnomalyDetectionService, "_create_model") as mock_create:
            mock_model = MagicMock()
            mock_model.score_one.side_effect = RuntimeError("Model error")
            mock_create.return_value = mock_model

            with patch.object(
                AnomalyDetectionService, "_create_preprocessors", return_value=[]
            ):
                service = AnomalyDetectionService(anomaly_config)
                result = service.process_data_point(sample_telemetry_data)

        assert result.is_anomaly is False
        assert result.severity == "unknown"
        assert "error" in result.context

    def test_process_primes_model_on_unseen_feature(self):
        """Test unseen feature errors trigger schema warm-up instead of hard failure."""
        from off_key_mqtt_radar.detector import AnomalyDetectionService

        config = SimpleNamespace(
            model_type="isolation_forest",
            thresholds={"medium": 0.6, "high": 0.8, "critical": 0.9},
            checkpoint_interval=1000,
        )

        with patch.object(AnomalyDetectionService, "_create_model") as mock_create:
            mock_model = MagicMock()
            mock_model.score_one.side_effect = [
                ValueError("Feature 'timestamp' has not been seen during learning."),
                0.4,
            ]
            mock_model.learn_one = MagicMock()
            mock_create.return_value = mock_model

            with patch.object(
                AnomalyDetectionService, "_create_preprocessors", return_value=[]
            ):
                service = AnomalyDetectionService(config)
                result = service.process_data_point(
                    {"value": 10.0, "timestamp": 1739441120.0}
                )

        assert result.is_anomaly is False
        assert result.severity == "low"
        assert result.context["schema_warmup"] is True
        assert result.context["unseen_feature"] == "timestamp"
        assert service.processed_count == 1
        mock_model.learn_one.assert_called_once_with(
            {"value": 10.0, "timestamp": 1739441120.0}
        )

    def test_process_primes_scaler_on_first_unseen_feature(self):
        """Test scaler cold-start uses schema warm-up instead of failing permanently."""
        from onad.transform.preprocessing.scaler import StandardScaler
        from off_key_mqtt_radar.detector import AnomalyDetectionService

        config = SimpleNamespace(
            model_type="isolation_forest",
            thresholds={"medium": 0.6, "high": 0.8, "critical": 0.9},
            checkpoint_interval=1000,
            preprocessing_steps=[],
            subscription_topics=[],
            sensor_key_strategy="full_hierarchy",
        )

        with patch.object(AnomalyDetectionService, "_create_model") as mock_create:
            mock_model = MagicMock()
            mock_model.score_one.return_value = 0.4
            mock_model.learn_one = MagicMock()
            mock_create.return_value = mock_model

            with patch.object(
                AnomalyDetectionService,
                "_create_preprocessors",
                return_value=[StandardScaler()],
            ):
                service = AnomalyDetectionService(config)
                result = service.process_data_point({"TopLevelPart": 42.0})

        assert result.is_anomaly is False
        assert result.severity == "low"
        assert result.context["schema_warmup"] is True
        assert result.context["unseen_feature"] == "TopLevelPart"
        assert service.processed_count == 1
        mock_model.learn_one.assert_called_once()

    def test_preprocessor_learning_is_stage_consistent(self):
        """Test each preprocessor learns from the preceding stage output."""
        from off_key_mqtt_radar.detector import AnomalyDetectionService

        config = SimpleNamespace(
            model_type="isolation_forest",
            thresholds={"medium": 0.6, "high": 0.8, "critical": 0.9},
            checkpoint_interval=1000,
            preprocessing_steps=[],
            subscription_topics=[],
            sensor_key_strategy="full_hierarchy",
        )

        first = MagicMock()
        first.transform_one.side_effect = lambda sample: {"scaled": sample["x"] + 1.0}
        first.learn_one = MagicMock()

        second = MagicMock()
        second.transform_one.side_effect = lambda sample: {
            "projected": sample["scaled"] * 2.0
        }
        second.learn_one = MagicMock()

        with patch.object(AnomalyDetectionService, "_create_model") as mock_create:
            mock_model = MagicMock()
            mock_model.score_one.return_value = 0.1
            mock_model.learn_one = MagicMock()
            mock_create.return_value = mock_model

            with patch.object(
                AnomalyDetectionService,
                "_create_preprocessors",
                return_value=[first, second],
            ):
                service = AnomalyDetectionService(config)
                service.process_data_point({"x": 3.0})

        first.learn_one.assert_called_once_with({"x": 3.0})
        second.learn_one.assert_called_once_with({"scaled": 4.0})

    def test_unseen_feature_after_learning_triggers_single_warmup_then_recovers(self):
        """Test new feature warm-up recovers and subsequent point processes normally."""
        from onad.transform.preprocessing.scaler import StandardScaler
        from off_key_mqtt_radar.detector import AnomalyDetectionService

        config = SimpleNamespace(
            model_type="isolation_forest",
            thresholds={"medium": 0.6, "high": 0.8, "critical": 0.9},
            checkpoint_interval=1000,
            preprocessing_steps=[],
            subscription_topics=[],
            sensor_key_strategy="full_hierarchy",
        )

        with patch.object(AnomalyDetectionService, "_create_model") as mock_create:
            mock_model = MagicMock()
            mock_model.score_one.return_value = 0.2
            mock_model.learn_one = MagicMock()
            mock_create.return_value = mock_model

            with patch.object(
                AnomalyDetectionService,
                "_create_preprocessors",
                return_value=[StandardScaler()],
            ):
                service = AnomalyDetectionService(config)
                first = service.process_data_point({"A": 1.0})
                second = service.process_data_point({"B": 2.0})
                third = service.process_data_point({"B": 2.5})

        assert first.context["schema_warmup"] is True
        assert first.context["unseen_feature"] == "A"
        assert second.context["schema_warmup"] is True
        assert second.context["unseen_feature"] == "B"
        assert "schema_warmup" not in (third.context or {})
        assert third.severity == "low"
        assert mock_model.score_one.call_count == 1

    def test_checkpoint_schema_signature_mismatch_raises_error(self):
        """Test checkpoint restore raises ValueError on schema signature mismatch."""
        from off_key_mqtt_radar.detector import AnomalyDetectionService

        config = SimpleNamespace(
            model_type="isolation_forest",
            preprocessing_steps=[
                {"type": "standard_scaler", "params": {"with_std": True}}
            ],
            subscription_topics=["charger/+/live-telemetry/TopLevelPart/SubMetricA"],
            sensor_key_strategy="full_hierarchy",
        )

        mismatch_checkpoint = {
            "model": MagicMock(),
            "preprocessors": [],
            "processed_count": 10,
            "anomaly_count": 1,
            "config": SimpleNamespace(model_type="isolation_forest"),
            "schema_signature": "different-signature",
        }

        with patch.object(
            AnomalyDetectionService,
            "_load_and_verify_checkpoint",
            return_value=mismatch_checkpoint,
        ):
            with pytest.raises(
                ValueError, match="Checkpoint schema signature does not match"
            ):
                AnomalyDetectionService.from_checkpoint("ignored.pkl", config)


class TestResilientAnomalyDetector:
    """Tests for ResilientAnomalyDetector with circuit breaker."""

    def test_process_success(self, anomaly_config, sample_telemetry_data):
        """Test successful processing through resilient detector."""
        from off_key_mqtt_radar.detector import (
            AnomalyDetectionService,
            ResilientAnomalyDetector,
        )

        with patch.object(AnomalyDetectionService, "_create_model") as mock_create:
            mock_model = MagicMock()
            mock_model.score_one.return_value = 0.5
            mock_model.learn_one = MagicMock()
            mock_create.return_value = mock_model

            with patch.object(
                AnomalyDetectionService, "_create_preprocessors", return_value=[]
            ):
                primary_service = AnomalyDetectionService(anomaly_config)
                detector = ResilientAnomalyDetector(primary_service)

                result = detector.process_with_resilience(sample_telemetry_data)

        assert result.anomaly_score == 0.5
        assert detector.circuit_breaker_open is False

    def test_fallback_on_error(self, anomaly_config, sample_telemetry_data):
        """Test fallback processing when primary service fails."""
        from off_key_mqtt_radar.detector import (
            AnomalyDetectionService,
            ResilientAnomalyDetector,
        )

        with patch.object(AnomalyDetectionService, "_create_model") as mock_create:
            mock_model = MagicMock()
            mock_model.score_one.side_effect = RuntimeError("Model error")
            mock_create.return_value = mock_model

            with patch.object(
                AnomalyDetectionService, "_create_preprocessors", return_value=[]
            ):
                primary_service = AnomalyDetectionService(anomaly_config)
                detector = ResilientAnomalyDetector(primary_service)

                result = detector.process_with_resilience(sample_telemetry_data)

        assert "fallback_reason" in result.context
        assert detector.error_count > 0

    def test_circuit_breaker_opens_on_high_error_rate(
        self, anomaly_config, sample_telemetry_data
    ):
        """Test circuit breaker opens when error rate exceeds threshold."""
        from off_key_mqtt_radar.detector import (
            AnomalyDetectionService,
            ResilientAnomalyDetector,
            ServiceState,
        )

        with patch.object(AnomalyDetectionService, "_create_model") as mock_create:
            mock_model = MagicMock()
            mock_model.score_one.side_effect = RuntimeError("Model error")
            mock_create.return_value = mock_model

            with patch.object(
                AnomalyDetectionService, "_create_preprocessors", return_value=[]
            ):
                primary_service = AnomalyDetectionService(anomaly_config)
                detector = ResilientAnomalyDetector(primary_service)
                detector.error_threshold = 0.05  # Lower threshold for test

                # Generate enough errors to trigger circuit breaker
                for _ in range(15):
                    detector.process_with_resilience(sample_telemetry_data)

        assert detector.circuit_breaker_open is True
        assert detector.state == ServiceState.DEGRADED

    def test_get_health_info(self, anomaly_config):
        """Test health info retrieval."""
        from off_key_mqtt_radar.detector import (
            AnomalyDetectionService,
            ResilientAnomalyDetector,
        )

        with patch.object(AnomalyDetectionService, "_create_model"):
            with patch.object(
                AnomalyDetectionService, "_create_preprocessors", return_value=[]
            ):
                primary_service = AnomalyDetectionService(anomaly_config)
                detector = ResilientAnomalyDetector(primary_service)

                health_info = detector.get_health_info()

        assert "state" in health_info
        assert "circuit_breaker_open" in health_info
        assert "error_count" in health_info


class TestSecurityValidator:
    """Tests for SecurityValidator input sanitization."""

    def test_validate_valid_data(self):
        """Test validation of valid data."""
        from off_key_mqtt_radar.detector import SecurityValidator

        validator = SecurityValidator()
        data = {"cpu": 45.5, "memory": 1024, "temp": 65.2}
        result = validator.validate_and_sanitize(data)

        assert result == {"cpu": 45.5, "memory": 1024.0, "temp": 65.2}

    def test_validate_rejects_non_dict(self):
        """Test that non-dict input is rejected."""
        from off_key_mqtt_radar.detector import SecurityValidator

        validator = SecurityValidator()

        with pytest.raises(ValueError, match="Input must be a dictionary"):
            validator.validate_and_sanitize("not a dict")

    def test_validate_rejects_too_many_features(self):
        """Test rejection of data with too many features."""
        from off_key_mqtt_radar.detector import SecurityValidator

        validator = SecurityValidator(max_feature_count=5)
        data = {f"feature_{i}": i for i in range(10)}

        with pytest.raises(ValueError, match="Too many features"):
            validator.validate_and_sanitize(data)

    def test_validate_handles_string_values(self):
        """Test conversion of string values to numeric."""
        from off_key_mqtt_radar.detector import SecurityValidator

        validator = SecurityValidator()
        data = {"numeric_string": "42.5", "text": "hello"}
        result = validator.validate_and_sanitize(data)

        assert result["numeric_string"] == 42.5
        # Text is hashed to numeric value
        assert "text" in result
        assert isinstance(result["text"], float)

    def test_validate_filters_out_of_range_values(self):
        """Test that out-of-range values are filtered."""
        from off_key_mqtt_radar.detector import SecurityValidator

        validator = SecurityValidator()
        data = {"normal": 100.0, "too_big": 1e11, "too_small": -1e11}
        result = validator.validate_and_sanitize(data)

        assert "normal" in result
        assert "too_big" not in result
        assert "too_small" not in result

    def test_validate_drops_metadata_timestamp_keys(self):
        """Test that metadata keys like timestamp are excluded from features."""
        from off_key_mqtt_radar.detector import SecurityValidator

        validator = SecurityValidator()
        data = {"value": 12.5, "timestamp": "2026-02-13T12:23:40Z"}
        result = validator.validate_and_sanitize(data)

        assert result == {"value": 12.5}


class TestMemoryManager:
    """Tests for MemoryManager."""

    def test_get_memory_usage(self):
        """Test memory usage retrieval."""
        from off_key_mqtt_radar.detector import MemoryManager

        manager = MemoryManager()
        usage = manager.get_memory_usage()

        assert usage > 0
        assert isinstance(usage, float)

    def test_should_cleanup(self):
        """Test cleanup threshold check."""
        from off_key_mqtt_radar.detector import MemoryManager

        # Set very high threshold that won't be exceeded
        manager = MemoryManager(max_memory_mb=1000000, cleanup_threshold=0.8)
        assert manager.should_cleanup() is False

    def test_force_cleanup(self):
        """Test forced garbage collection."""
        from off_key_mqtt_radar.detector import MemoryManager

        manager = MemoryManager()
        freed = manager.force_cleanup()

        # freed can be positive, negative, or zero depending on GC
        assert isinstance(freed, float)
