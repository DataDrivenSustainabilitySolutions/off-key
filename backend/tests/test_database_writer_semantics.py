"""Tests for persisted anomaly semantics in RADAR database writer."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from off_key_mqtt_radar.database import (
    ANOMALY_TABLE,
    DatabaseWriter,
    MULTIVARIATE_TELEMETRY_TYPE,
)
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


def test_anomaly_table_metadata_includes_value_type_column():
    assert "value_type" in ANOMALY_TABLE.columns.keys()


@pytest.mark.asyncio
async def test_retry_batch_persists_value_type(monkeypatch):
    config = MagicMock()
    config.db_batch_size = 100
    config.db_batch_timeout = 1.0
    config.db_write_enabled = True

    sleep_mock = AsyncMock()
    monkeypatch.setattr("off_key_mqtt_radar.database.asyncio.sleep", sleep_mock)

    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    session_factory = MagicMock(return_value=session_cm)
    writer = DatabaseWriter(config, session_factory=session_factory)
    batch_snapshot = [
        _build_result(aligned_vector=False, tail_pvalue=0.0042, anomaly_score=0.02)
    ]

    await writer._retry_failed_batch(batch_snapshot=batch_snapshot)

    first_insert_stmt = session.execute.await_args_list[0].args[0]
    first_row = first_insert_stmt._multi_values[0][0]
    assert first_row["value_type"] == "tail_pvalue"


@pytest.mark.asyncio
async def test_retry_batch_logs_exhaustion_and_increments_errors(monkeypatch, caplog):
    config = MagicMock()
    config.db_batch_size = 100
    config.db_batch_timeout = 1.0
    config.db_write_enabled = True

    sleep_mock = AsyncMock()
    monkeypatch.setattr("off_key_mqtt_radar.database.asyncio.sleep", sleep_mock)

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=RuntimeError("db down"))
    session.commit = AsyncMock()

    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    writer = DatabaseWriter(config, session_factory=MagicMock(return_value=session_cm))
    retry_batch = [
        _build_result(aligned_vector=False, tail_pvalue=0.001, anomaly_score=0.02)
    ]

    with caplog.at_level("ERROR"):
        await writer._retry_failed_batch(batch_snapshot=retry_batch)

    assert writer.total_errors == 1
    assert writer.total_written == 0
    assert any(
        "event=radar.db_retry_exhausted" in rec.message for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_flush_batch_requeues_snapshot_on_unexpected_retry_exception():
    config = MagicMock()
    config.db_batch_size = 100
    config.db_batch_timeout = 1.0
    config.db_write_enabled = True

    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None

    writer = DatabaseWriter(config, session_factory=MagicMock(return_value=session_cm))
    anomaly = _build_result(aligned_vector=False, tail_pvalue=0.002, anomaly_score=0.02)
    writer.write_queue = [anomaly]

    writer._execute_upsert = AsyncMock(side_effect=RuntimeError("flush failed"))
    writer._retry_failed_batch = AsyncMock(side_effect=RuntimeError("retry crashed"))

    await writer._flush_batch()

    assert writer.write_queue == [anomaly]
    assert writer.total_errors == 2
