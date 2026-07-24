"""Tests for detector resilience, input validation, and memory utilities."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from off_key_mqtt_radar.feature_validation import TelemetryFeatureValidator
from off_key_mqtt_radar.memory import MemoryManager
from off_key_mqtt_radar.models import AnomalyResult
from off_key_mqtt_radar.resilience import ResilientAnomalyDetector, ServiceState


def _result(score: float = 0.5, *, is_anomaly: bool = False) -> AnomalyResult:
    return AnomalyResult(
        anomaly_score=score,
        is_anomaly=is_anomaly,
        severity="unknown",
        timestamp=datetime.now(UTC),
        model_info={"strategy": "static_baseline"},
        raw_data={"value": 1.0},
        context={},
    )


class _DetectorDouble:
    def __init__(
        self,
        result: AnomalyResult | None = None,
        error: Exception | None = None,
    ):
        self.result = result or _result()
        self.error = error
        self.refresh_background_state = MagicMock()

    def process_data_point(self, _data, _topic=None, _charger_id=None):
        if self.error is not None:
            raise self.error
        return self.result

    def get_model_info(self):
        return {"strategy": "static_baseline"}


class TestResilientAnomalyDetector:
    def test_success_uses_primary_static_service(self):
        primary = _DetectorDouble(_result(0.7))
        detector = ResilientAnomalyDetector(primary)

        result = detector.process_with_resilience({"value": 2.0})

        assert result.anomaly_score == 0.7
        assert detector.circuit_breaker_open is False

    def test_diagnostic_fallback_never_generates_an_alarm(self):
        primary = _DetectorDouble(error=RuntimeError("model error"))
        detector = ResilientAnomalyDetector(primary)

        result = detector.process_with_resilience({"value": 100.0})

        assert result.is_anomaly is False
        assert result.severity == "unknown"
        assert result.context["fallback_reason"] == "model error"
        assert result.context["model_used"] == "statistical"
        assert detector.error_count == 1

    def test_explicit_fallback_service_is_identified(self):
        primary = _DetectorDouble(error=RuntimeError("primary failed"))
        fallback = _DetectorDouble(_result(0.2))
        detector = ResilientAnomalyDetector(primary, fallback)

        result = detector.process_with_resilience({"value": 3.0})

        assert result.context["fallback_reason"] == "primary failed"
        assert result.context["model_used"] == "fallback"

    def test_circuit_breaker_opens_on_repeated_errors(self):
        primary = _DetectorDouble(error=RuntimeError("model error"))
        detector = ResilientAnomalyDetector(primary)

        for _ in range(11):
            detector.process_with_resilience({"value": 1.0})

        assert detector.circuit_breaker_open is True
        assert detector.state == ServiceState.DEGRADED

    def test_health_refreshes_background_training_state(self):
        primary = _DetectorDouble()
        detector = ResilientAnomalyDetector(primary)

        health = detector.get_health_info()

        primary.refresh_background_state.assert_called_once_with()
        assert health["state"] == "healthy"
        assert health["primary_service_stats"]["strategy"] == "static_baseline"
        assert health["uptime_seconds"] >= 0


class TestTelemetryFeatureValidator:
    def test_validate_valid_data(self):
        validator = TelemetryFeatureValidator()
        result = validator.validate_and_sanitize(
            {"cpu": 45.5, "memory": 1024, "temp": 65.2}
        )
        assert result == {"cpu": 45.5, "memory": 1024.0, "temp": 65.2}

    def test_validate_rejects_non_dict(self):
        with pytest.raises(ValueError, match="Input must be a dictionary"):
            TelemetryFeatureValidator().validate_and_sanitize("not a dict")

    def test_validate_rejects_too_many_features(self):
        data = {f"feature_{index}": index for index in range(10)}
        with pytest.raises(ValueError, match="Too many features"):
            TelemetryFeatureValidator(max_feature_count=5).validate_and_sanitize(data)

    def test_validate_handles_string_values(self):
        result = TelemetryFeatureValidator().validate_and_sanitize(
            {"numeric_string": "42.5", "text": "hello"}
        )
        assert result["numeric_string"] == 42.5
        assert "text" not in result

    def test_validate_filters_out_of_range_values(self):
        result = TelemetryFeatureValidator().validate_and_sanitize(
            {
                "normal": 100.0,
                "too_big": 1e11,
                "too_small": -1e11,
                "not_finite": float("nan"),
            }
        )
        assert result == {"normal": 100.0}

    def test_validate_preserves_boolean_telemetry(self):
        result = TelemetryFeatureValidator().validate_and_sanitize(
            {"enabled": True, "faulted": False}
        )
        assert result == {"enabled": 1.0, "faulted": 0.0}

    def test_validate_drops_metadata_timestamp_keys(self):
        result = TelemetryFeatureValidator().validate_and_sanitize(
            {"value": 12.5, "timestamp": "2026-02-13T12:23:40Z"}
        )
        assert result == {"value": 12.5}


class TestMemoryManager:
    def test_get_memory_usage(self):
        usage = MemoryManager().get_memory_usage()
        assert usage > 0
        assert isinstance(usage, float)

    def test_should_cleanup(self):
        manager = MemoryManager(max_memory_mb=1_000_000, cleanup_threshold=0.8)
        assert manager.should_cleanup() is False

    def test_force_cleanup(self):
        assert isinstance(MemoryManager().force_cleanup(), float)
