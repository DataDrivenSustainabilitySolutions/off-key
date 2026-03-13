"""Tests for DatabaseWriter batching and health behavior."""

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
