"""Tests for persisted anomaly semantics in RADAR database writer."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from off_key_mqtt_radar.database import DatabaseWriter, MULTIVARIATE_TELEMETRY_TYPE
from off_key_mqtt_radar.models import AnomalyResult


def _build_result(
    *,
    aligned_vector: bool,
    tail_pvalue,
    anomaly_score: float,
) -> AnomalyResult:
    return AnomalyResult(
        anomaly_score=anomaly_score,
        is_anomaly=True,
        severity="high",
        timestamp=datetime.now(timezone.utc),
        model_info={"model_type": "isolation_forest"},
        raw_data={"value": 1.0},
        topic="charger/charger-1/live-telemetry/sine",
        charger_id="charger-1",
        context={
            "score_window": {"tail_pvalue": tail_pvalue},
            "alignment": {"aligned_vector": aligned_vector},
        },
    )


def test_database_writer_uses_tail_pvalue_for_persisted_anomaly_value():
    result = _build_result(aligned_vector=True, tail_pvalue=0.0042, anomaly_score=0.018)
    assert DatabaseWriter._derive_anomaly_value(result) == 0.0042


def test_database_writer_falls_back_to_anomaly_score_when_tail_pvalue_missing():
    result = _build_result(aligned_vector=False, tail_pvalue=None, anomaly_score=0.011)
    assert DatabaseWriter._derive_anomaly_value(result) == 0.011


def test_database_writer_marks_multivariate_anomaly_type():
    result = _build_result(aligned_vector=True, tail_pvalue=0.001, anomaly_score=0.01)
    assert DatabaseWriter._derive_anomaly_type(result) == "ml_tailprob_multivariate"


def test_database_writer_marks_univariate_anomaly_type():
    result = _build_result(aligned_vector=False, tail_pvalue=0.01, anomaly_score=0.01)
    assert DatabaseWriter._derive_anomaly_type(result) == "ml_tailprob_univariate"


def test_database_writer_uses_canonical_multivariate_telemetry_type():
    config = MagicMock()
    writer = DatabaseWriter(config, session_factory=MagicMock())
    result = _build_result(aligned_vector=True, tail_pvalue=0.004, anomaly_score=0.01)

    assert writer._derive_telemetry_type(result) == MULTIVARIATE_TELEMETRY_TYPE


def test_database_writer_uses_topic_telemetry_type_for_univariate():
    config = MagicMock()
    writer = DatabaseWriter(config, session_factory=MagicMock())
    result = _build_result(aligned_vector=False, tail_pvalue=0.004, anomaly_score=0.01)

    assert writer._derive_telemetry_type(result) == "sine"
