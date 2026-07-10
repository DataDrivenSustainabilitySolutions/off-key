from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from off_key_core.utils.enum import HealthStatus
from off_key_core.utils.mqtt_topics import TopicMetadataExtractor
from off_key_mqtt_proxy.client.models import MQTTMessage
from off_key_mqtt_proxy.telemetry import (
    DatabaseWriter,
    ParseFailure,
    ParseSuccess,
    WriteBatch,
)


def _writer() -> DatabaseWriter:
    config = MagicMock()
    config.batch_size = 100
    config.batch_timeout = 5.0
    config.graceful_shutdown_timeout = 5.0
    return DatabaseWriter(
        config=config,
        session_factory=MagicMock(),
        topic_extractor=TopicMetadataExtractor(),
    )


@pytest.mark.asyncio
async def test_parse_telemetry_message_converts_offset_timestamp_to_utc():
    writer = _writer()
    message = MQTTMessage(
        topic="charger/charger-1/live-telemetry/sine",
        payload={"timestamp": "2024-01-01T12:00:00+02:00", "value": "2.5"},
        timestamp=datetime.now(timezone.utc),
        qos=0,
        retain=False,
    )

    result = await writer._parse_telemetry_message(message)

    assert isinstance(result, ParseSuccess)
    assert result.record.timestamp == datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc)
    assert result.record.created.tzinfo is not None


@pytest.mark.asyncio
async def test_parse_telemetry_message_treats_naive_timestamp_as_utc():
    writer = _writer()
    message = MQTTMessage(
        topic="charger/charger-1/live-telemetry/sine",
        payload={"timestamp": "2024-01-01T12:00:00", "value": "2.5"},
        timestamp=datetime.now(timezone.utc),
        qos=0,
        retain=False,
    )

    result = await writer._parse_telemetry_message(message)

    assert isinstance(result, ParseSuccess)
    assert result.record.timestamp == datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_parse_telemetry_message_invalid_topic_returns_safe_failure():
    writer = _writer()
    message = MQTTMessage(
        topic="charger/abc/live-telemetry",
        payload={"timestamp": "2024-01-01T12:00:00+00:00", "value": "2.5"},
        timestamp=datetime.now(timezone.utc),
        qos=0,
        retain=False,
    )

    result = await writer._parse_telemetry_message(message)

    assert isinstance(result, ParseFailure)
    assert not result.is_error


@pytest.mark.asyncio
async def test_parse_telemetry_message_invalid_timestamp_returns_safe_failure():
    writer = _writer()
    message = MQTTMessage(
        topic="charger/charger-1/live-telemetry/sine",
        payload={"timestamp": "not-a-date", "value": "2.5"},
        timestamp=datetime.now(timezone.utc),
        qos=0,
        retain=False,
    )

    result = await writer._parse_telemetry_message(message)

    assert isinstance(result, ParseFailure)
    assert not result.is_error
    assert result.reason == "Invalid timestamp format"


@pytest.mark.asyncio
async def test_parse_telemetry_message_invalid_timezone_offset_returns_safe_failure():
    writer = _writer()
    message = MQTTMessage(
        topic="charger/charger-1/live-telemetry/sine",
        payload={"timestamp": "2024-01-01T12:00:00+25:00", "value": "2.5"},
        timestamp=datetime.now(timezone.utc),
        qos=0,
        retain=False,
    )

    result = await writer._parse_telemetry_message(message)

    assert isinstance(result, ParseFailure)
    assert not result.is_error
    assert result.reason == "Invalid timestamp format"


@pytest.mark.asyncio
async def test_parse_telemetry_message_utc_suffix_timestamp():
    writer = _writer()
    message = MQTTMessage(
        topic="charger/charger-1/live-telemetry/sine",
        payload={"timestamp": "2024-01-01T12:00:00Z", "value": "2.5"},
        timestamp=datetime.now(timezone.utc),
        qos=0,
        retain=False,
    )

    result = await writer._parse_telemetry_message(message)

    assert isinstance(result, ParseSuccess)
    assert result.record.timestamp == datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_parse_telemetry_message_unix_epoch_timestamp():
    writer = _writer()
    message = MQTTMessage(
        topic="charger/charger-1/live-telemetry/sine",
        payload={"timestamp": 1704110400, "value": "2.5"},
        timestamp=datetime.now(timezone.utc),
        qos=0,
        retain=False,
    )

    result = await writer._parse_telemetry_message(message)

    assert isinstance(result, ParseSuccess)
    assert result.record.timestamp == datetime.fromtimestamp(
        1704110400, tz=timezone.utc
    )


@pytest.mark.asyncio
async def test_parse_telemetry_message_invalid_value_is_treated_as_none():
    writer = _writer()
    message = MQTTMessage(
        topic="charger/charger-1/live-telemetry/sine",
        payload={"timestamp": "2024-01-01T12:00:00+00:00", "value": "not-a-number"},
        timestamp=datetime.now(timezone.utc),
        qos=0,
        retain=False,
    )

    result = await writer._parse_telemetry_message(message)

    assert isinstance(result, ParseSuccess)
    assert result.record.value is None


@pytest.mark.asyncio
async def test_process_batch_returns_true_for_empty_batch():
    writer = _writer()
    batch = WriteBatch()
    assert await writer._process_batch(batch) is True


@pytest.mark.asyncio
async def test_process_batch_uses_rowcount_for_written_records():
    writer = _writer()

    message = MQTTMessage(
        topic="charger/charger-1/live-telemetry/sine",
        payload={"timestamp": "2024-01-01T12:00:00+00:00", "value": "2.5"},
        timestamp=datetime.now(timezone.utc),
        qos=0,
        retain=False,
    )
    result = await writer._parse_telemetry_message(message)
    assert isinstance(result, ParseSuccess)

    session = AsyncMock()
    execute_insert_result = MagicMock()
    execute_insert_result.rowcount = 1
    session.execute.side_effect = [
        AsyncMock(),
        execute_insert_result,
        AsyncMock(),
    ]
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session
    session_ctx.__aexit__.return_value = False

    writer._session_factory = MagicMock(return_value=session_ctx)

    batch = WriteBatch(records=[result.record, result.record])
    assert await writer._process_batch(batch) is True
    assert writer.total_records_written == 1


@pytest.mark.asyncio
async def test_process_batch_falls_back_to_batch_size_when_rowcount_is_none():
    writer = _writer()

    message = MQTTMessage(
        topic="charger/charger-1/live-telemetry/sine",
        payload={"timestamp": "2024-01-01T12:00:00+00:00", "value": "2.5"},
        timestamp=datetime.now(timezone.utc),
        qos=0,
        retain=False,
    )
    result = await writer._parse_telemetry_message(message)
    assert isinstance(result, ParseSuccess)

    session = AsyncMock()
    execute_insert_result = MagicMock()
    execute_insert_result.rowcount = None
    session.execute.side_effect = [
        AsyncMock(),
        execute_insert_result,
        AsyncMock(),
    ]
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session
    session_ctx.__aexit__.return_value = False

    writer._session_factory = MagicMock(return_value=session_ctx)

    batch = WriteBatch(records=[result.record, result.record, result.record])
    assert await writer._process_batch(batch) is True
    assert writer.total_records_written == 3


@pytest.mark.asyncio
async def test_process_batch_falls_back_to_batch_size_when_rowcount_is_negative():
    writer = _writer()

    message = MQTTMessage(
        topic="charger/charger-1/live-telemetry/sine",
        payload={"timestamp": "2024-01-01T12:00:00+00:00", "value": "2.5"},
        timestamp=datetime.now(timezone.utc),
        qos=0,
        retain=False,
    )
    result = await writer._parse_telemetry_message(message)
    assert isinstance(result, ParseSuccess)

    session = AsyncMock()
    execute_insert_result = MagicMock()
    execute_insert_result.rowcount = -1
    session.execute.side_effect = [
        AsyncMock(),
        execute_insert_result,
        AsyncMock(),
    ]
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session
    session_ctx.__aexit__.return_value = False

    writer._session_factory = MagicMock(return_value=session_ctx)

    batch = WriteBatch(records=[result.record])
    assert await writer._process_batch(batch) is True
    assert writer.total_records_written == 1


@pytest.mark.asyncio
async def test_process_batch_integrity_error_treated_as_success(monkeypatch):
    writer = _writer()
    message = MQTTMessage(
        topic="charger/charger-1/live-telemetry/sine",
        payload={"timestamp": "2024-01-01T12:00:00+00:00", "value": "2.5"},
        timestamp=datetime.now(timezone.utc),
        qos=0,
        retain=False,
    )
    result = await writer._parse_telemetry_message(message)
    assert isinstance(result, ParseSuccess)

    session = AsyncMock()
    session.execute = AsyncMock(
        side_effect=[AsyncMock(), IntegrityError("dup", None, None)]
    )
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session
    session_ctx.__aexit__.return_value = False
    writer._session_factory = MagicMock(return_value=session_ctx)
    writer._update_chargers_after_failure = AsyncMock()

    batch = WriteBatch(records=[result.record])
    assert await writer._process_batch(batch) is True
    writer._update_chargers_after_failure.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_batch_sqlalchemy_error_propagates_as_failure():
    writer = _writer()
    message = MQTTMessage(
        topic="charger/charger-1/live-telemetry/sine",
        payload={"timestamp": "2024-01-01T12:00:00+00:00", "value": "2.5"},
        timestamp=datetime.now(timezone.utc),
        qos=0,
        retain=False,
    )
    result = await writer._parse_telemetry_message(message)
    assert isinstance(result, ParseSuccess)

    session = AsyncMock()
    session.execute = AsyncMock(side_effect=[AsyncMock(), SQLAlchemyError("db down")])
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session
    session_ctx.__aexit__.return_value = False
    writer._session_factory = MagicMock(return_value=session_ctx)

    batch = WriteBatch(records=[result.record])
    assert await writer._process_batch(batch) is False


@pytest.mark.asyncio
async def test_batch_retry_failure_increments_failed_record_metrics(monkeypatch):
    writer = _writer()
    writer.config.get_jittered_backoff_delay = lambda attempt: 0.0

    message = MQTTMessage(
        topic="charger/charger-1/live-telemetry/sine",
        payload={"timestamp": "2024-01-01T12:00:00+00:00", "value": "2.5"},
        timestamp=datetime.now(timezone.utc),
        qos=0,
        retain=False,
    )
    result_one = await writer._parse_telemetry_message(message)
    assert isinstance(result_one, ParseSuccess)

    message_two = MQTTMessage(
        topic="charger/charger-1/live-telemetry/sine",
        payload={"timestamp": "2024-01-01T12:00:01+00:00", "value": "3.5"},
        timestamp=datetime.now(timezone.utc),
        qos=0,
        retain=False,
    )
    result_two = await writer._parse_telemetry_message(message_two)
    assert isinstance(result_two, ParseSuccess)

    batch_id = "test-batch"
    writer.processing_batches[batch_id] = WriteBatch(
        records=[result_one.record, result_two.record]
    )
    writer._process_batch = AsyncMock(return_value=False)
    monkeypatch.setattr("off_key_mqtt_proxy.telemetry.asyncio.sleep", AsyncMock())

    await writer._process_batch_with_retry(batch_id)

    assert writer._process_batch.await_count == 4
    assert writer.total_records_failed == 2
    assert writer.total_batches_failed == 1
    assert writer.processing_batches.get(batch_id) is None


@pytest.mark.asyncio
async def test_batch_retry_success_keeps_failed_metrics_at_zero(monkeypatch):
    writer = _writer()
    writer.config.get_jittered_backoff_delay = lambda attempt: 0.0

    message = MQTTMessage(
        topic="charger/charger-1/live-telemetry/sine",
        payload={"timestamp": "2024-01-01T12:00:00+00:00", "value": "2.5"},
        timestamp=datetime.now(timezone.utc),
        qos=0,
        retain=False,
    )
    result = await writer._parse_telemetry_message(message)
    assert isinstance(result, ParseSuccess)

    batch_id = "test-batch"
    writer.processing_batches[batch_id] = WriteBatch(records=[result.record])
    writer._process_batch = AsyncMock(return_value=True)
    monkeypatch.setattr("off_key_mqtt_proxy.telemetry.asyncio.sleep", AsyncMock())

    await writer._process_batch_with_retry(batch_id)

    assert writer._process_batch.await_count == 1
    assert writer.total_records_failed == 0
    assert writer.total_batches_failed == 0
    assert writer.processing_batches.get(batch_id) is None


def test_get_health_status_prefers_unhealthy_when_multiple_conditions_conflict():
    writer = _writer()
    writer.total_batches_processed = 1
    writer.total_batches_failed = 1
    writer.write_latency_sum = 3.0
    writer.write_latency_count = 1

    health = writer.get_health_status()

    assert health.status is HealthStatus.UNHEALTHY


def test_get_health_status_marks_degraded_when_only_secondary_metrics_match():
    writer = _writer()
    writer.total_batches_processed = 1
    writer.total_records_written = 1
    writer.write_latency_sum = 3.0
    writer.write_latency_count = 1
    writer.processing_batches["batch_0"] = WriteBatch()

    health = writer.get_health_status()

    assert health.status is HealthStatus.DEGRADED


def test_get_health_status_marks_unhealthy_with_excessive_processing_backlog():
    writer = _writer()
    for idx in range(11):
        writer.processing_batches[f"batch_{idx}"] = WriteBatch()

    health = writer.get_health_status()

    assert health.status is HealthStatus.UNHEALTHY
