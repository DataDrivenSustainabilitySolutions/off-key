"""Tests for persisted anomaly semantics in RADAR database writer."""

from datetime import datetime, timezone

from off_key_mqtt_radar.database import DatabaseWriter
from off_key_mqtt_radar.models import AnomalyResult


def _build_result(
    *,
    aligned_vector: bool,
    zscore,
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
            "score_window": {"zscore": zscore},
            "alignment": {"aligned_vector": aligned_vector},
        },
    )


def test_database_writer_uses_zscore_for_persisted_anomaly_value():
    result = _build_result(aligned_vector=True, zscore=4.25, anomaly_score=0.018)
    assert DatabaseWriter._derive_anomaly_value(result) == 4.25


def test_database_writer_falls_back_to_anomaly_score_when_zscore_missing():
    result = _build_result(aligned_vector=False, zscore=None, anomaly_score=0.011)
    assert DatabaseWriter._derive_anomaly_value(result) == 0.011


def test_database_writer_marks_multivariate_anomaly_type():
    result = _build_result(aligned_vector=True, zscore=5.0, anomaly_score=0.01)
    assert DatabaseWriter._derive_anomaly_type(result) == "ml_zscore_multivariate"


def test_database_writer_marks_univariate_anomaly_type():
    result = _build_result(aligned_vector=False, zscore=3.2, anomaly_score=0.01)
    assert DatabaseWriter._derive_anomaly_type(result) == "ml_zscore_univariate"
