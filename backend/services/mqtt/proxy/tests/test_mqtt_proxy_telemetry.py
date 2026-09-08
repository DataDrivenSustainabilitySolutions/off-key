import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from off_key_core.utils.enum import HealthStatus
from off_key_core.utils.mqtt_topics import TopicMetadataExtractor
from off_key_mqtt_proxy.client.models import MQTTMessage
from off_key_mqtt_proxy.telemetry import DatabaseWriter
from off_key_mqtt_proxy.telemetry_models import ParseFailure, ParseSuccess, WriteBatch
from off_key_mqtt_proxy.telemetry_parsing import parse_telemetry_message
from sqlalchemy.exc import IntegrityError, SQLAlchemyError


def _writer() -> DatabaseWriter:
    config = MagicMock()
    config.batch_size = 100
    config.batch_timeout = 5.0
    config.graceful_shutdown_timeout = 5.0
    config.health_monitor_interval = 60.0
    return DatabaseWriter(
        config=config,
        session_factory=MagicMock(),
        topic_extractor=TopicMetadataExtractor(),
    )


def test_parse_telemetry_message_converts_offset_timestamp_to_utc():
    writer = _writer()
    message = MQTTMessage(
        topic="device/evCharger/charger-1/sine",
        payload={"timestamp": "2024-01-01T12:00:00+02:00", "value": "2.5"},
        timestamp=datetime.now(UTC),
        qos=0,
        retain=False,
    )

    result = parse_telemetry_message(message, writer.topic_extractor)

    assert isinstance(result, ParseSuccess)
    assert result.record.timestamp == datetime(2024, 1, 1, 10, 0, tzinfo=UTC)
    assert result.record.created.tzinfo is not None


def test_parse_telemetry_message_treats_naive_timestamp_as_utc():
    writer = _writer()
    message = MQTTMessage(
        topic="device/evCharger/charger-1/sine",
        payload={"timestamp": "2024-01-01T12:00:00", "value": "2.5"},
        timestamp=datetime.now(UTC),
        qos=0,
        retain=False,
    )

    result = parse_telemetry_message(message, writer.topic_extractor)

    assert isinstance(result, ParseSuccess)
    assert result.record.timestamp == datetime(2024, 1, 1, 12, 0, tzinfo=UTC)


def test_parse_telemetry_message_invalid_topic_returns_safe_failure():
    writer = _writer()
    message = MQTTMessage(
        topic="device/evCharger/abc",
        payload={"timestamp": "2024-01-01T12:00:00+00:00", "value": "2.5"},
        timestamp=datetime.now(UTC),
        qos=0,
        retain=False,
    )

    result = parse_telemetry_message(message, writer.topic_extractor)

    assert isinstance(result, ParseFailure)
    assert not result.is_error


def test_parse_telemetry_message_invalid_timestamp_returns_safe_failure():
    writer = _writer()
    message = MQTTMessage(
        topic="device/evCharger/charger-1/sine",
        payload={"timestamp": "not-a-date", "value": "2.5"},
        timestamp=datetime.now(UTC),
        qos=0,
        retain=False,
    )

    result = parse_telemetry_message(message, writer.topic_extractor)

    assert isinstance(result, ParseFailure)
    assert not result.is_error
    assert result.reason == "Invalid timestamp format"


def test_parse_telemetry_message_invalid_timezone_offset_returns_safe_failure():
    writer = _writer()
    message = MQTTMessage(
        topic="device/evCharger/charger-1/sine",
        payload={"timestamp": "2024-01-01T12:00:00+25:00", "value": "2.5"},
        timestamp=datetime.now(UTC),
        qos=0,
        retain=False,
    )

    result = parse_telemetry_message(message, writer.topic_extractor)

    assert isinstance(result, ParseFailure)
    assert not result.is_error
    assert result.reason == "Invalid timestamp format"


def test_parse_telemetry_message_utc_suffix_timestamp():
    writer = _writer()
    message = MQTTMessage(
        topic="device/evCharger/charger-1/sine",
        payload={"timestamp": "2024-01-01T12:00:00Z", "value": "2.5"},
        timestamp=datetime.now(UTC),
        qos=0,
        retain=False,
    )

    result = parse_telemetry_message(message, writer.topic_extractor)

    assert isinstance(result, ParseSuccess)
    assert result.record.timestamp == datetime(2024, 1, 1, 12, 0, tzinfo=UTC)


def test_parse_telemetry_message_unix_epoch_timestamp():
    writer = _writer()
    message = MQTTMessage(
        topic="device/evCharger/charger-1/sine",
        payload={"timestamp": 1704110400, "value": "2.5"},
        timestamp=datetime.now(UTC),
        qos=0,
        retain=False,
    )

    result = parse_telemetry_message(message, writer.topic_extractor)

    assert isinstance(result, ParseSuccess)
    assert result.record.timestamp == datetime.fromtimestamp(1704110400, tz=UTC)


@pytest.mark.parametrize(
    "value", [None, True, False, "not-a-number", "NaN", "Infinity"]
)
def test_parse_telemetry_message_invalid_value_returns_safe_failure(value):
    writer = _writer()
    message = MQTTMessage(
        topic="device/evCharger/charger-1/sine",
        payload={"timestamp": "2024-01-01T12:00:00+00:00", "value": value},
        timestamp=datetime.now(UTC),
        qos=0,
        retain=False,
    )

    result = parse_telemetry_message(message, writer.topic_extractor)

    assert isinstance(result, ParseFailure)
    assert not result.is_error
    assert result.reason == "Invalid telemetry value"


@pytest.mark.parametrize("timestamp", [None, True, "1e100"])
def test_parse_telemetry_message_rejects_present_invalid_timestamp(timestamp):
    writer = _writer()
    message = MQTTMessage(
        topic="device/evCharger/charger-1/sine",
        payload={"timestamp": timestamp, "value": 2.5},
        timestamp=datetime.now(UTC),
        qos=0,
        retain=False,
    )

    result = parse_telemetry_message(message, writer.topic_extractor)

    assert isinstance(result, ParseFailure)
    assert not result.is_error
    assert result.reason == "Invalid timestamp format"


def test_parse_telemetry_message_uses_ingestion_time_without_timestamp():
    writer = _writer()
    before = datetime.now(UTC)
    message = MQTTMessage(
        topic="device/evCharger/0/currentDc",
        payload={"value": 12.5},
        timestamp=before,
        qos=0,
        retain=False,
    )

    result = parse_telemetry_message(message, writer.topic_extractor)

    assert isinstance(result, ParseSuccess)
    assert result.record.charger_id == "0"
    assert result.record.telemetry_type == "currentDc"
    assert result.record.value == 12.5
    assert before <= result.record.timestamp <= datetime.now(UTC)


@pytest.mark.asyncio
async def test_process_batch_returns_true_for_empty_batch():
    writer = _writer()
    batch = WriteBatch()
    assert await writer._process_batch(batch) is True


@pytest.mark.asyncio
async def test_process_batch_uses_rowcount_for_written_records():
    writer = _writer()

    message = MQTTMessage(
        topic="device/evCharger/charger-1/sine",
        payload={"timestamp": "2024-01-01T12:00:00+00:00", "value": "2.5"},
        timestamp=datetime.now(UTC),
        qos=0,
        retain=False,
    )
    result = parse_telemetry_message(message, writer.topic_extractor)
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
        topic="device/evCharger/charger-1/sine",
        payload={"timestamp": "2024-01-01T12:00:00+00:00", "value": "2.5"},
        timestamp=datetime.now(UTC),
        qos=0,
        retain=False,
    )
    result = parse_telemetry_message(message, writer.topic_extractor)
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
        topic="device/evCharger/charger-1/sine",
        payload={"timestamp": "2024-01-01T12:00:00+00:00", "value": "2.5"},
        timestamp=datetime.now(UTC),
        qos=0,
        retain=False,
    )
    result = parse_telemetry_message(message, writer.topic_extractor)
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
async def test_process_batch_integrity_error_rolls_back_and_reports_failure():
    writer = _writer()
    message = MQTTMessage(
        topic="device/evCharger/charger-1/sine",
        payload={"timestamp": "2024-01-01T12:00:00+00:00", "value": "2.5"},
        timestamp=datetime.now(UTC),
        qos=0,
        retain=False,
    )
    result = parse_telemetry_message(message, writer.topic_extractor)
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

    batch = WriteBatch(records=[result.record])
    assert await writer._process_batch(batch) is False
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
    assert writer.total_records_written == 0


@pytest.mark.asyncio
async def test_process_batch_sqlalchemy_error_propagates_as_failure():
    writer = _writer()
    message = MQTTMessage(
        topic="device/evCharger/charger-1/sine",
        payload={"timestamp": "2024-01-01T12:00:00+00:00", "value": "2.5"},
        timestamp=datetime.now(UTC),
        qos=0,
        retain=False,
    )
    result = parse_telemetry_message(message, writer.topic_extractor)
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
        topic="device/evCharger/charger-1/sine",
        payload={"timestamp": "2024-01-01T12:00:00+00:00", "value": "2.5"},
        timestamp=datetime.now(UTC),
        qos=0,
        retain=False,
    )
    result_one = parse_telemetry_message(message, writer.topic_extractor)
    assert isinstance(result_one, ParseSuccess)

    message_two = MQTTMessage(
        topic="device/evCharger/charger-1/sine",
        payload={"timestamp": "2024-01-01T12:00:01+00:00", "value": "3.5"},
        timestamp=datetime.now(UTC),
        qos=0,
        retain=False,
    )
    result_two = parse_telemetry_message(message_two, writer.topic_extractor)
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
    assert writer.processing_batches[batch_id].size() == 2
    await writer._process_batch_with_retry(batch_id)
    assert writer.total_records_failed == 2
    assert writer.total_batches_failed == 1
    writer._process_batch.return_value = True
    await writer._process_batch_with_retry(batch_id)
    assert not writer.processing_batches


@pytest.mark.asyncio
async def test_batch_retry_success_keeps_failed_metrics_at_zero(monkeypatch):
    writer = _writer()
    writer.config.get_jittered_backoff_delay = lambda attempt: 0.0

    message = MQTTMessage(
        topic="device/evCharger/charger-1/sine",
        payload={"timestamp": "2024-01-01T12:00:00+00:00", "value": "2.5"},
        timestamp=datetime.now(UTC),
        qos=0,
        retain=False,
    )
    result = parse_telemetry_message(message, writer.topic_extractor)
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


def _message() -> MQTTMessage:
    return MQTTMessage(
        topic="device/evCharger/charger-1/sine",
        payload={"timestamp": datetime.now(UTC).isoformat(), "value": 1.0},
        timestamp=datetime.now(UTC),
        qos=0,
        retain=False,
    )


@pytest.mark.asyncio
async def test_stalled_database_bounds_batches_and_backpressures_producers():
    writer = _writer()
    writer.batch_size = 1
    entered = asyncio.Event()
    release = asyncio.Event()
    processed = []

    async def persist(batch):
        entered.set()
        await release.wait()
        processed.extend(batch.records)
        return True

    writer._process_batch = persist
    await writer.start()
    producer = None
    try:
        await writer.write_telemetry_message(_message())
        await asyncio.wait_for(entered.wait(), 1)
        await writer.write_telemetry_message(_message())
        producer = asyncio.create_task(writer.write_telemetry_message(_message()))
        await asyncio.sleep(0)
        assert not producer.done()
        assert writer.pending_batch.size() == 1
        assert len(writer.processing_batches) == 1
        release.set()
        await asyncio.wait_for(producer, 1)
        await writer.stop()
        assert len(processed) == 3
        assert not writer.processing_batches
        assert writer.pending_batch.size() == 0
    finally:
        release.set()
        if producer and not producer.done():
            producer.cancel()
        await writer.stop()


@pytest.mark.asyncio
async def test_shutdown_releases_waiting_producers_and_retains_unwritten_batches():
    writer = _writer()
    writer.batch_size = 1
    writer.config.graceful_shutdown_timeout = 0.01
    entered = asyncio.Event()

    async def persist(_batch):
        entered.set()
        await asyncio.Event().wait()

    writer._process_batch = persist
    await writer.start()
    await writer.write_telemetry_message(_message())
    await asyncio.wait_for(entered.wait(), 1)
    await writer.write_telemetry_message(_message())
    producer = asyncio.create_task(writer.write_telemetry_message(_message()))
    await asyncio.sleep(0)
    with pytest.raises(TimeoutError):
        await writer.stop()
    with pytest.raises(RuntimeError, match="stopping"):
        await producer
    assert writer.pending_batch.size() == 1
    assert sum(batch.size() for batch in writer.processing_batches.values()) == 1
    assert writer._writer_task.done()
    assert writer._health_task.done()


@pytest.mark.asyncio
@pytest.mark.parametrize("sqlstate", ["22003", "23514", "54000"])
async def test_permanent_record_failure_does_not_block_valid_telemetry(sqlstate):
    from sqlalchemy.exc import DBAPIError

    writer = _writer()
    writer.max_retries = 0
    session = AsyncMock()
    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session
    session_ctx.__aexit__.return_value = False
    writer._session_factory = MagicMock(return_value=session_ctx)
    writer._upsert_chargers = AsyncMock()
    writer._update_charger_statuses = AsyncMock()
    committed = []
    staged = []

    async def execute(statement):
        params = statement.compile().params
        sensors = [value for key, value in params.items() if key.startswith("type_m")]
        if "bad" in sensors:
            error = Exception("index row size exceeds maximum")
            error.sqlstate = sqlstate
            raise DBAPIError("insert", None, error)
        staged.extend(sensors)
        return MagicMock(rowcount=len(sensors))

    async def commit():
        committed.extend(staged)
        staged.clear()

    session.execute.side_effect = execute
    session.commit.side_effect = commit
    session.rollback.side_effect = staged.clear
    for sensor in ("good-before", "bad", "good-after"):
        message = _message()
        message.topic = f"device/evCharger/charger-1/{sensor}"
        await writer.write_telemetry_message(message)
    await writer._trigger_batch_processing()
    await writer.write_telemetry_message(_message())
    await writer._trigger_batch_processing()

    assert committed == ["good-before", "good-after", "sine"]
    assert session.rollback.await_count == 2
    assert writer.total_records_written == 3
    assert writer.get_performance_metrics().total_records_rejected == 1
    assert not writer.processing_batches
    assert writer.pending_batch.size() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sqlstate", ["08006", "40001", "42501", "42P01", "23503", "54000", None]
)
async def test_non_record_database_errors_retain_batch(sqlstate):
    from sqlalchemy.exc import DBAPIError

    writer = _writer()
    writer.max_retries = 0
    session = AsyncMock()
    error = Exception("database failure")
    error.sqlstate = sqlstate
    session.execute.side_effect = DBAPIError("insert", None, error)
    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session
    session_ctx.__aexit__.return_value = False
    writer._session_factory = MagicMock(return_value=session_ctx)
    await writer.write_telemetry_message(_message())
    await writer._trigger_batch_processing()
    assert len(writer.processing_batches) == 1
    assert next(iter(writer.processing_batches.values())).size() == 1
    assert writer.total_records_rejected == 0
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", [False, asyncio.CancelledError()])
async def test_isolation_retains_only_unfinished_records_after_interruption(
    interruption,
):
    from off_key_mqtt_proxy.telemetry import PermanentRecordError

    writer = _writer()
    for _ in range(3):
        await writer.write_telemetry_message(_message())
    batch = writer.pending_batch
    original = list(batch.records)
    writer._process_batch = AsyncMock(
        side_effect=[PermanentRecordError("bad batch"), True, interruption]
    )
    if isinstance(interruption, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await writer._persist_owned_batch(batch)
    else:
        assert await writer._persist_owned_batch(batch) is False
    assert batch.records == original[1:]
    assert batch.isolate_records
    writer._process_batch = AsyncMock(return_value=True)
    assert await writer._persist_owned_batch(batch) is True
    assert writer._process_batch.await_count == 2
    assert not batch.records
