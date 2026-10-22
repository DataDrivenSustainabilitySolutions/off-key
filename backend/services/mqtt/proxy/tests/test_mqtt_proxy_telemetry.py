"""Telemetry parsing and batched database writes in the MQTT proxy."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from off_key_core.utils.enum import HealthStatus
from off_key_core.utils.mqtt_topics import TopicMetadataExtractor
from off_key_mqtt_proxy.client.models import MQTTMessage
from off_key_mqtt_proxy.telemetry import DatabaseWriter, PermanentRecordError
from off_key_mqtt_proxy.telemetry_models import (
    ParseFailure,
    ParseSuccess,
    WriteBatch,
    WriteStatus,
)
from off_key_mqtt_proxy.telemetry_parsing import parse_telemetry_message
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError

TOPIC = "telemetry/charger-1/sine"
VALID = {"timestamp": "2024-01-01T12:00:00+00:00", "value": "2.5"}


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


def _message(topic=TOPIC, payload=None) -> MQTTMessage:
    if payload is None:
        payload = {"timestamp": datetime.now(UTC).isoformat(), "value": 1.0}
    return MQTTMessage(
        topic=topic,
        payload=payload,
        timestamp=datetime.now(UTC),
        qos=0,
        retain=False,
    )


def _parse(payload, topic=TOPIC):
    return parse_telemetry_message(_message(topic, payload), TopicMetadataExtractor())


def _record(**overrides):
    result = _parse({**VALID, **overrides})
    assert isinstance(result, ParseSuccess)
    return result.record


def _use_session(writer: DatabaseWriter) -> AsyncMock:
    session = AsyncMock()
    session_ctx = AsyncMock()
    session_ctx.__aenter__.return_value = session
    writer._session_factory = MagicMock(return_value=session_ctx)
    return session


def _database_error(sqlstate, message="database failure") -> DBAPIError:
    error = Exception(message)
    error.sqlstate = sqlstate
    return DBAPIError("insert", None, error)


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        ("2024-01-01T12:00:00+02:00", datetime(2024, 1, 1, 10, 0, tzinfo=UTC)),
        ("2024-01-01T12:00:00", datetime(2024, 1, 1, 12, 0, tzinfo=UTC)),
        ("2024-01-01T12:00:00Z", datetime(2024, 1, 1, 12, 0, tzinfo=UTC)),
        (1704110400, datetime.fromtimestamp(1704110400, tz=UTC)),
    ],
    ids=["offset", "naive_is_utc", "utc_suffix", "unix_epoch"],
)
def test_parse_normalizes_timestamps_to_utc(timestamp, expected):
    result = _parse({"timestamp": timestamp, "value": "2.5"})

    assert isinstance(result, ParseSuccess)
    assert result.record.timestamp == expected
    assert result.record.value == 2.5
    assert result.record.created.tzinfo is not None


def test_parse_uses_ingestion_time_without_timestamp():
    before = datetime.now(UTC)

    result = _parse({"value": 12.5}, topic="telemetry/0/currentDc")

    assert isinstance(result, ParseSuccess)
    record = result.record
    assert (record.charger_id, record.telemetry_type, record.value) == (
        "0",
        "currentDc",
        12.5,
    )
    assert before <= record.timestamp <= datetime.now(UTC)


@pytest.mark.parametrize(
    ("topic", "payload", "reason", "is_error"),
    [
        pytest.param(
            "telemetry/abc",
            VALID,
            "Topic metadata extraction failed",
            False,
            id="topic",
        ),
        *[
            pytest.param(
                TOPIC,
                {**VALID, "timestamp": timestamp},
                "Invalid timestamp format",
                False,
                id=f"timestamp-{timestamp}",
            )
            for timestamp in [
                "not-a-date",
                "2024-01-01T12:00:00+25:00",
                None,
                True,
                "1e100",
            ]
        ],
        *[
            pytest.param(
                TOPIC,
                {**VALID, "value": value},
                "Invalid telemetry value",
                False,
                id=f"value-{value}",
            )
            for value in [None, True, False, "not-a-number", "NaN", "Infinity"]
        ],
        pytest.param(TOPIC, 5, "Unexpected parsing error", True, id="bare-number"),
    ],
)
def test_parse_rejects_malformed_telemetry_without_raising(
    topic, payload, reason, is_error
):
    result = _parse(payload, topic)

    assert isinstance(result, ParseFailure)
    assert (result.reason, result.is_error) == (reason, is_error)


async def test_process_batch_returns_true_for_empty_batch():
    assert await _writer()._process_batch(WriteBatch()) is True


@pytest.mark.parametrize(
    ("rowcount", "records", "written"),
    [(1, 2, 1), (None, 3, 3), (-1, 1, 1)],
    ids=["driver_count", "unknown_count", "negative_count"],
)
async def test_process_batch_counts_rows_reported_by_the_driver(
    rowcount, records, written
):
    writer = _writer()
    session = _use_session(writer)
    session.execute.return_value = MagicMock(rowcount=rowcount)

    assert await writer._process_batch(WriteBatch(records=[_record()] * records))

    assert writer.total_records_written == written
    assert writer.last_successful_write_at is not None
    session.commit.assert_awaited_once()


@pytest.mark.parametrize(
    "error",
    [
        IntegrityError("dup", None, None),
        SQLAlchemyError("db down"),
        RuntimeError("driver crashed"),
    ],
    ids=["integrity", "sqlalchemy", "unexpected"],
)
async def test_process_batch_rolls_back_and_reports_failure(error):
    writer = _writer()
    session = _use_session(writer)
    session.execute.side_effect = error

    assert await writer._process_batch(WriteBatch(records=[_record()])) is False

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
    assert writer.last_successful_write_at is None
    assert writer.total_records_written == 0


async def test_retry_gives_up_after_max_attempts_and_keeps_the_batch(monkeypatch):
    writer = _writer()
    writer.config.get_jittered_backoff_delay = lambda attempt: 0.0
    monkeypatch.setattr("off_key_mqtt_proxy.telemetry.asyncio.sleep", AsyncMock())
    batch_id = "test-batch"
    writer.processing_batches[batch_id] = WriteBatch(
        records=[_record(), _record(timestamp="2024-01-01T12:00:01+00:00")]
    )
    writer._process_batch = AsyncMock(return_value=False)

    await writer._process_batch_with_retry(batch_id)

    assert writer._process_batch.await_count == 4
    assert (writer.total_records_failed, writer.total_batches_failed) == (2, 1)
    assert writer.processing_batches[batch_id].size() == 2

    # A retained batch is counted as failed once; a later success releases it.
    await writer._process_batch_with_retry(batch_id)
    writer._process_batch = AsyncMock(return_value=True)
    await writer._process_batch_with_retry(batch_id)

    writer._process_batch.assert_awaited_once()
    assert (writer.total_records_failed, writer.total_batches_failed) == (2, 1)
    assert not writer.processing_batches


@pytest.mark.parametrize(
    ("metrics", "processing_batches", "expected"),
    [
        ({}, 0, "healthy"),
        ({"total_batches_processed": 97, "total_batches_failed": 3}, 0, "degraded"),
        ({"total_batches_processed": 1, "total_batches_failed": 1}, 0, "unhealthy"),
        ({"write_latency_sum": 3.0, "write_latency_count": 1}, 0, "degraded"),
        ({"write_latency_sum": 6.0, "write_latency_count": 1}, 0, "unhealthy"),
        ({"write_latency_sum": 3.0, "write_latency_count": 1}, 1, "degraded"),
        ({}, 6, "degraded"),
        ({}, 11, "unhealthy"),
        # Failure-driven unhealthy must not be softened by milder signals.
        (
            {
                "total_batches_processed": 1,
                "total_batches_failed": 1,
                "write_latency_sum": 3.0,
                "write_latency_count": 1,
            },
            6,
            "unhealthy",
        ),
    ],
    ids=[
        "healthy",
        "some_failures",
        "many_failures",
        "slow_writes",
        "very_slow_writes",
        "slow_writes_small_backlog",
        "backlog",
        "excessive_backlog",
        "conflicting_signals",
    ],
)
def test_health_status_reflects_failures_latency_and_backlog(
    metrics, processing_batches, expected
):
    writer = _writer()
    for name, value in metrics.items():
        setattr(writer, name, value)
    for index in range(processing_batches):
        writer.processing_batches[f"batch_{index}"] = WriteBatch()

    assert writer.get_health_status().status == HealthStatus(expected)


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


@pytest.mark.parametrize("sqlstate", ["22003", "23514", "54000"])
async def test_permanent_record_failure_does_not_block_valid_telemetry(sqlstate):
    writer = _writer()
    writer.max_retries = 0
    session = _use_session(writer)
    committed = []
    staged = []

    async def execute(statement):
        params = statement.compile().params
        sensors = [value for key, value in params.items() if key.startswith("type_m")]
        if "bad" in sensors:
            raise _database_error(sqlstate, "index row size exceeds maximum")
        staged.extend(sensors)
        return MagicMock(rowcount=len(sensors))

    async def commit():
        committed.extend(staged)
        staged.clear()

    session.execute.side_effect = execute
    session.commit.side_effect = commit
    session.rollback.side_effect = staged.clear
    for sensor in ("good-before", "bad", "good-after"):
        await writer.write_telemetry_message(_message(f"telemetry/charger-1/{sensor}"))
    await writer._trigger_batch_processing()
    await writer.write_telemetry_message(_message())
    await writer._trigger_batch_processing()

    assert committed == ["good-before", "good-after", "sine"]
    assert session.rollback.await_count == 2
    assert writer.total_records_written == 3
    assert writer.get_performance_metrics().total_records_rejected == 1
    assert not writer.processing_batches
    assert writer.pending_batch.size() == 0


@pytest.mark.parametrize(
    "sqlstate", ["08006", "40001", "42501", "42P01", "23503", "54000", None]
)
async def test_non_record_database_errors_retain_batch(sqlstate):
    writer = _writer()
    writer.max_retries = 0
    session = _use_session(writer)
    session.execute.side_effect = _database_error(sqlstate)

    await writer.write_telemetry_message(_message())
    await writer._trigger_batch_processing()

    assert len(writer.processing_batches) == 1
    assert next(iter(writer.processing_batches.values())).size() == 1
    assert writer.total_records_rejected == 0
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()


@pytest.mark.parametrize("interruption", [False, asyncio.CancelledError()])
async def test_isolation_retains_only_unfinished_records_after_interruption(
    interruption,
):
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


def test_queue_reports_pending_and_in_flight_records_against_two_batches():
    writer = _writer()
    writer.pending_batch.add_record(_record())
    writer.processing_batches["a"] = WriteBatch(records=[_record(), _record()])

    assert writer.queued_records == 3
    assert writer.queue_capacity == 200


@pytest.mark.parametrize(
    ("status", "retrying"),
    [
        (WriteStatus.PROCESSING, False),
        (WriteStatus.RETRYING, True),
        (WriteStatus.FAILED, True),
    ],
)
def test_retrying_reflects_in_flight_batch_status(status, retrying):
    writer = _writer()
    writer.processing_batches["a"] = WriteBatch(status=status)

    assert writer.is_retrying is retrying
