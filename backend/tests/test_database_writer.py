"""Tests for DatabaseWriter batching and health behavior."""

import asyncio
from contextlib import suppress
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture
def db_config():
    config = MagicMock()
    config.db_batch_size = 2
    config.db_batch_timeout = 5.0
    config.db_write_enabled = True
    return config


@pytest.mark.asyncio
async def test_write_anomaly_adds_to_queue(db_config, sample_anomaly_result):
    from off_key_mqtt_radar.database import DatabaseWriter

    writer = DatabaseWriter(db_config, session_factory=AsyncMock())
    writer._flush_batch = AsyncMock()

    await writer.write_anomaly(sample_anomaly_result)

    assert len(writer.write_queue) == 1
    writer._flush_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_anomaly_flushes_when_batch_size_reached(
    db_config,
    sample_anomaly_result,
):
    from off_key_mqtt_radar.database import DatabaseWriter

    writer = DatabaseWriter(db_config, session_factory=AsyncMock())
    writer._flush_batch = AsyncMock()

    await writer.write_anomaly(sample_anomaly_result)
    await writer.write_anomaly(sample_anomaly_result)

    writer._flush_batch.assert_awaited_once()


def test_build_evidence_record_preserves_static_inference_context(
    db_config, sample_anomaly_result, monkeypatch
):
    from off_key_mqtt_radar.database import DatabaseWriter

    monkeypatch.setattr(
        "off_key_mqtt_radar.database.get_radar_checkpoint_settings",
        lambda: SimpleNamespace(SERVICE_ID="svc-static"),
    )
    result = replace(
        sample_anomaly_result,
        is_anomaly=False,
        context={
            "alignment": {
                "aligned_vector": True,
                "required_sensors": ["L1", "L2", "L3"],
            },
            "static_conformal": {
                "phase": "ready",
                "p_value": 0.02,
                "e_value": 3.5,
                "e_value_is_infinite": False,
                "log_e_value": 1.25,
                "restarted_martingale": 42.0,
                "restarted_martingale_is_infinite": False,
                "log_restarted_martingale": 3.74,
                "restarted_ville_threshold": 100.0,
                "alarm_fired": False,
                "tested_count": 7,
            },
        },
    )
    writer = DatabaseWriter(db_config, session_factory=AsyncMock())

    records = writer._build_evidence_records([result])

    assert records == [
        {
            "service_id": "svc-static",
            "timestamp": result.timestamp,
            "sequence_number": 7,
            "charger_id": result.charger_id,
            "sensor_set": ["L1", "L2", "L3"],
            "p_value": 0.02,
            "e_value": 3.5,
            "e_value_is_infinite": False,
            "log_e_value": 1.25,
            "restarted_martingale": 42.0,
            "restarted_martingale_is_infinite": False,
            "log_restarted_martingale": 3.74,
            "threshold": 100.0,
            "alarm": False,
        }
    ]


def test_build_evidence_record_normalizes_infinite_values(
    db_config, sample_anomaly_result, monkeypatch
):
    from off_key_mqtt_radar.database import DatabaseWriter

    monkeypatch.setattr(
        "off_key_mqtt_radar.database.get_radar_checkpoint_settings",
        lambda: SimpleNamespace(SERVICE_ID="svc-static"),
    )
    result = replace(
        sample_anomaly_result,
        context={
            "static_conformal": {
                "phase": "ready",
                "p_value": 0.0,
                "e_value": float("inf"),
                "e_value_is_infinite": True,
                "log_e_value": float("inf"),
                "restarted_martingale": float("inf"),
                "restarted_martingale_is_infinite": True,
                "log_restarted_martingale": float("inf"),
                "restarted_ville_threshold": 100.0,
                "alarm_fired": True,
                "tested_count": 8,
            }
        },
    )

    writer = DatabaseWriter(db_config, session_factory=AsyncMock())
    record = writer._build_evidence_records([result])[0]

    assert record["e_value"] is None
    assert record["log_e_value"] is None
    assert record["restarted_martingale"] is None
    assert record["log_restarted_martingale"] is None
    assert record["e_value_is_infinite"] is True
    assert record["restarted_martingale_is_infinite"] is True


@pytest.mark.asyncio
async def test_flush_persists_ready_evidence_without_anomaly(
    db_config, sample_anomaly_result, mock_session_factory, monkeypatch
):
    from off_key_mqtt_radar.database import DatabaseWriter

    monkeypatch.setattr(
        "off_key_mqtt_radar.database.get_radar_checkpoint_settings",
        lambda: SimpleNamespace(SERVICE_ID="svc-static"),
    )
    result = replace(
        sample_anomaly_result,
        is_anomaly=False,
        context={
            "static_conformal": {
                "phase": "ready",
                "p_value": 0.25,
                "e_value": 1.0,
                "e_value_is_infinite": False,
                "log_e_value": 0.0,
                "restarted_martingale": 2.0,
                "restarted_martingale_is_infinite": False,
                "log_restarted_martingale": 0.69,
                "restarted_ville_threshold": 100.0,
                "alarm_fired": False,
                "tested_count": 1,
            }
        },
    )
    writer = DatabaseWriter(db_config, session_factory=mock_session_factory)
    writer._execute_upsert = AsyncMock()
    writer._execute_evidence_upsert = AsyncMock()
    writer.write_queue.append(result)

    await writer._flush_batch()

    writer._execute_upsert.assert_awaited_once_with(
        mock_session_factory.return_value.__aenter__.return_value, [], []
    )
    evidence_rows = writer._execute_evidence_upsert.await_args.args[1]
    assert evidence_rows[0]["p_value"] == 0.25
    assert writer.total_evidence_written == 1
    assert writer.total_written == 0


def test_get_health_status_disabled_when_writing_off(db_config):
    from off_key_mqtt_radar.database import DatabaseWriter

    db_config.db_write_enabled = False
    writer = DatabaseWriter(db_config, session_factory=AsyncMock())

    assert writer.get_health_status()["status"] == "disabled"


def test_get_health_status_unhealthy_when_task_missing(db_config):
    from off_key_mqtt_radar.database import DatabaseWriter

    writer = DatabaseWriter(db_config, session_factory=AsyncMock())
    status = writer.get_health_status()

    assert status["status"] == "unhealthy"
    assert status["reason"] == "writer_task_stopped"


def test_get_health_status_healthy_when_task_running(db_config):
    from off_key_mqtt_radar.database import DatabaseWriter

    writer = DatabaseWriter(db_config, session_factory=AsyncMock())
    writer._writer_task = MagicMock()
    writer._writer_task.done.return_value = False

    status = writer.get_health_status()

    assert status["status"] == "healthy"


@pytest.mark.asyncio
async def test_test_connection_uses_session_factory(db_config):
    from off_key_mqtt_radar.database import DatabaseWriter

    session = AsyncMock()
    query_result = MagicMock()
    query_result.fetchone.return_value = (1,)
    session.execute = AsyncMock(return_value=query_result)
    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session
    session_ctx.__aexit__.return_value = None
    session_factory = MagicMock(return_value=session_ctx)

    writer = DatabaseWriter(db_config, session_factory=session_factory)
    await writer._test_connection()

    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_flushes_remaining_records_when_cancelled(db_config, monkeypatch):
    from off_key_mqtt_radar.database import DatabaseWriter

    writer = DatabaseWriter(db_config, session_factory=AsyncMock())
    writer._writer_task = asyncio.create_task(asyncio.sleep(60))
    writer._flush_batch = AsyncMock()

    async def cancelled_wait_for(awaitable, timeout):  # noqa: ASYNC109
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise asyncio.CancelledError

    monkeypatch.setattr(
        "off_key_mqtt_radar.database.asyncio.wait_for",
        cancelled_wait_for,
    )

    with pytest.raises(asyncio.CancelledError):
        await writer.stop()

    writer._flush_batch.assert_awaited_once()
    writer._writer_task.cancel()
    with suppress(asyncio.CancelledError):
        await writer._writer_task
