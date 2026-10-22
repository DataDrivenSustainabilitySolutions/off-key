"""DatabaseWriter batching, retries and health, and the records it persists."""

import asyncio
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from off_key_mqtt_radar.database import DatabaseWriter
from off_key_mqtt_radar.models import AnomalyResult
from off_key_mqtt_radar.result_records import (
    MULTIVARIATE_TELEMETRY_TYPE,
    ResultProjector,
)
from off_key_mqtt_radar.tables import ANOMALY_TABLE


def _with_input_reference(result, context: dict) -> dict:
    """Attach the exact univariate telemetry observation used by the result."""
    return {
        **context,
        "alignment": {
            "aligned_vector": False,
            "input_timestamps": {"cpu": result.timestamp.isoformat()},
        },
    }


def _scored_result(
    *,
    aligned_vector: bool,
    anomaly_score: float,
    conformal_pvalue=None,
    required_sensors=None,
) -> AnomalyResult:
    return AnomalyResult(
        anomaly_score=anomaly_score,
        is_anomaly=True,
        severity="high",
        timestamp=datetime.now(UTC),
        model_info={"model_type": "isolation_forest"},
        raw_data={"value": 1.0},
        topic="telemetry/charger-1/sine",
        charger_id="charger-1",
        context={
            "static_conformal": {"p_value": conformal_pvalue},
            "alignment": {
                "aligned_vector": aligned_vector,
                "required_sensors": required_sensors,
            },
        },
    )


def _retrying_writer(session=None):
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session or AsyncMock()
    config = MagicMock(db_batch_size=100, db_batch_timeout=1.0, db_write_enabled=True)
    return DatabaseWriter(config, session_factory=MagicMock(return_value=session_cm))


@pytest.fixture
def db_config():
    config = MagicMock()
    config.db_batch_size = 2
    config.db_batch_timeout = 5.0
    config.max_queue_size = 100
    config.db_write_enabled = True
    config.sensor_freshness_seconds = 30.0
    return config


@pytest.mark.asyncio
async def test_write_result_adds_to_queue(db_config, sample_anomaly_result):
    writer = DatabaseWriter(db_config, session_factory=AsyncMock())
    writer._flush_batch = AsyncMock()

    await writer.write_result(sample_anomaly_result)

    assert len(writer.write_queue) == 1
    writer._flush_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_write_result_signals_writer_when_batch_size_reached(
    db_config,
    sample_anomaly_result,
):
    writer = DatabaseWriter(db_config, session_factory=AsyncMock())
    writer._flush_batch = AsyncMock()

    await writer.write_result(sample_anomaly_result)
    await writer.write_result(sample_anomaly_result)

    assert writer._flush_event.is_set()
    writer._flush_batch.assert_not_awaited()


@pytest.mark.asyncio
async def test_writer_loop_flushes_signalled_batch(db_config):
    writer = DatabaseWriter(db_config, session_factory=AsyncMock())
    writer._flush_batch = AsyncMock()

    task = asyncio.create_task(writer._writer_loop())
    writer._flush_event.set()
    await asyncio.sleep(0)
    writer._shutdown_event.set()
    writer._flush_event.set()
    await task

    assert writer._flush_batch.await_count >= 1


@pytest.mark.asyncio
async def test_write_result_applies_backpressure_at_queue_limit(
    db_config,
    sample_anomaly_result,
    mock_session_factory,
):
    db_config.max_queue_size = 2
    writer = DatabaseWriter(db_config, session_factory=mock_session_factory)
    writer._execute_upsert = AsyncMock(side_effect=RuntimeError("database unavailable"))
    writer._retry_failed_batch = AsyncMock(return_value=False)

    await writer.write_result(sample_anomaly_result)
    await writer.write_result(sample_anomaly_result)

    producers = [
        asyncio.create_task(writer.write_result(sample_anomaly_result))
        for _ in range(3)
    ]
    try:
        for _ in range(5):
            await writer._flush_batch()
            await asyncio.sleep(0)
            assert len(writer.write_queue) == 2
            assert all(not task.done() for task in producers)

        writer._execute_upsert = AsyncMock()
        await writer._flush_batch()
        await asyncio.sleep(0)
        assert sum(task.done() for task in producers) == 2
        assert len(writer.write_queue) == 2
        await writer._flush_batch()
        await asyncio.gather(*producers)
        await writer._flush_batch()
        assert writer.total_written == 5
        assert writer.write_queue == []
    finally:
        for task in producers:
            task.cancel()
        await asyncio.gather(*producers, return_exceptions=True)


@pytest.mark.asyncio
async def test_in_flight_batch_counts_towards_capacity_and_stop_wakes_producers(
    db_config,
    sample_anomaly_result,
    mock_session_factory,
):
    db_config.max_queue_size = 1
    writer = DatabaseWriter(db_config, session_factory=mock_session_factory)
    committing, release_commit = asyncio.Event(), asyncio.Event()

    async def slow_upsert(*args):
        committing.set()
        await release_commit.wait()

    writer._execute_upsert = slow_upsert
    await writer.write_result(sample_anomaly_result)
    flush = asyncio.create_task(writer._flush_batch())
    await committing.wait()
    producer = asyncio.create_task(writer.write_result(sample_anomaly_result))
    await asyncio.sleep(0)
    assert not producer.done()
    assert len(writer.write_queue) + writer._in_flight == 1

    stop = asyncio.create_task(writer.stop())
    try:
        with pytest.raises(RuntimeError, match="stopped"):
            await asyncio.wait_for(producer, timeout=1)
    finally:
        release_commit.set()
        await asyncio.gather(flush, stop)
    assert writer.total_written == 1
    assert writer.write_queue == []


def test_build_evidence_record_preserves_static_inference_context(
    db_config, sample_anomaly_result, monkeypatch
):
    result = replace(
        sample_anomaly_result,
        is_anomaly=False,
        context={
            "alignment": {
                "aligned_vector": True,
                "required_sensors": ["L1", "L2", "L3"],
                "input_timestamps": {
                    "L1": "2026-08-06T10:00:00Z",
                    "L2": "2026-08-06T10:00:00.100Z",
                    "L3": "2026-08-06T10:00:00.200Z",
                },
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
    writer = DatabaseWriter(
        db_config, session_factory=AsyncMock(), service_id="svc-static"
    )

    records = writer.projector._build_evidence_records([result])

    assert records == [
        {
            "service_id": "svc-static",
            "timestamp": datetime(2026, 8, 6, 10, 0, 0, 200000, tzinfo=UTC),
            "sequence_number": 7,
            "charger_id": result.charger_id,
            "sensor_set": ["L1", "L2", "L3"],
            "input_timestamps": {
                "L1": "2026-08-06T10:00:00+00:00",
                "L2": "2026-08-06T10:00:00.100000+00:00",
                "L3": "2026-08-06T10:00:00.200000+00:00",
            },
            "strategy": "static_baseline",
            "model_type": "isolation_forest",
            "p_value": 0.02,
            "anomaly_score": None,
            "e_value": 3.5,
            "e_value_is_infinite": False,
            "log_e_value": 1.25,
            "restarted_martingale": 42.0,
            "restarted_martingale_is_infinite": False,
            "log_restarted_martingale": 3.74,
            "tracker_results": [],
            "threshold": 100.0,
            "alarm": False,
        }
    ]


def test_build_adaptive_operational_evidence_and_anomaly_semantics(
    db_config, sample_anomaly_result, monkeypatch
):
    result = replace(
        sample_anomaly_result,
        anomaly_score=7.5,
        is_anomaly=True,
        model_info={"model_type": "aberrant_online_isolation_forest"},
        context={
            "model_type": "aberrant_online_isolation_forest",
            "alignment": {
                "aligned_vector": True,
                "required_sensors": ["L1", "L2"],
                "input_timestamps": {
                    "L1": "2026-08-06T10:00:00Z",
                    "L2": "2026-08-06T10:00:01Z",
                },
            },
            "adaptive_stream": {
                "phase": "operational",
                "sequence_number": 4,
                "anomaly_score": 7.5,
                "threshold": 5.0,
                "alarm_fired": True,
            },
        },
    )
    writer = DatabaseWriter(
        db_config, session_factory=AsyncMock(), service_id="svc-adaptive"
    )

    [evidence] = writer.projector._build_evidence_records([result])
    [anomaly], _ = writer.projector._build_records([result])

    assert evidence["strategy"] == "adaptive_stream"
    assert evidence["p_value"] is None
    assert evidence["anomaly_score"] == 7.5
    assert evidence["threshold"] == 5.0
    assert evidence["alarm"] is True
    assert anomaly["value_type"] == "anomaly_score"
    assert anomaly["anomaly_type"] == "ml_adaptive_stream_multivariate"
    assert anomaly["anomaly_value"] == 7.5
    calibration = replace(
        result,
        is_anomaly=False,
        context={
            **result.context,
            "adaptive_stream": {
                **result.context["adaptive_stream"],
                "phase": "calibration",
            },
        },
    )
    assert writer.projector._build_evidence_records([calibration]) == []


def test_build_evidence_record_normalizes_infinite_values(
    db_config, sample_anomaly_result, monkeypatch
):
    result = replace(
        sample_anomaly_result,
        context=_with_input_reference(
            sample_anomaly_result,
            {
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
        ),
    )

    writer = DatabaseWriter(
        db_config, session_factory=AsyncMock(), service_id="svc-static"
    )
    record = writer.projector._build_evidence_records([result])[0]

    assert record["e_value"] is None
    assert record["log_e_value"] is None
    assert record["restarted_martingale"] is None
    assert record["log_restarted_martingale"] is None
    assert record["e_value_is_infinite"] is True
    assert record["restarted_martingale_is_infinite"] is True


def test_build_evidence_record_preserves_generic_tracker_results(
    db_config, sample_anomaly_result, monkeypatch
):
    tracker_result = {
        "tracker_id": "mixture-cusum",
        "betting_function": "simple_mixture",
        "betting_parameters": {"n_grid": 64, "min_epsilon": 0.02},
        "alarm_statistic": "cusum",
        "statistic_value": float("inf"),
        "statistic_is_infinite": True,
        "log_statistic_value": float("inf"),
        "statistics": {
            "cusum": {
                "value": float("inf"),
                "is_infinite": True,
                "log_value": float("inf"),
            }
        },
        "e_value": 2.0,
        "e_value_is_infinite": False,
        "log_e_value": 0.69,
        "threshold": 25.0,
        "threshold_horizon": 100,
        "threshold_window_position": 9,
        "threshold_window_reset": False,
        "alarm_fired": True,
        "alarm_active": True,
        "alarm_count": 1,
        "tested_count": 9,
    }
    result = replace(
        sample_anomaly_result,
        context=_with_input_reference(
            sample_anomaly_result,
            {
                "static_conformal": {
                    "phase": "ready",
                    "p_value": 0.01,
                    "e_value": 2.0,
                    "e_value_is_infinite": False,
                    "log_e_value": 0.69,
                    "restarted_martingale": 4.0,
                    "restarted_martingale_is_infinite": False,
                    "log_restarted_martingale": 1.39,
                    "threshold": 25.0,
                    "alarm_fired": True,
                    "tested_count": 9,
                    "tracker_results": [tracker_result],
                }
            },
        ),
    )

    record = DatabaseWriter(
        db_config, session_factory=AsyncMock(), service_id="svc-ensemble"
    ).projector._build_evidence_records([result])[0]
    stored_tracker = record["tracker_results"][0]

    assert stored_tracker["tracker_id"] == "mixture-cusum"
    assert stored_tracker["statistic_value"] is None
    assert stored_tracker["statistic_is_infinite"] is True
    assert stored_tracker["statistics"]["cusum"]["value"] is None
    assert stored_tracker["threshold_horizon"] == 100
    assert stored_tracker["threshold_window_position"] == 9
    assert stored_tracker["threshold_window_reset"] is False
    assert record["threshold"] == 25.0


@pytest.mark.asyncio
async def test_flush_persists_ready_evidence_without_anomaly(
    db_config, sample_anomaly_result, mock_session_factory, monkeypatch
):
    result = replace(
        sample_anomaly_result,
        is_anomaly=False,
        context=_with_input_reference(
            sample_anomaly_result,
            {
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
        ),
    )
    writer = DatabaseWriter(
        db_config, session_factory=mock_session_factory, service_id="svc-static"
    )
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


def test_build_evidence_record_rejects_incomplete_input_references(
    db_config, sample_anomaly_result, monkeypatch
):
    result = replace(
        sample_anomaly_result,
        is_anomaly=False,
        context={
            "alignment": {
                "aligned_vector": True,
                "required_sensors": ["L1", "L2"],
                "input_timestamps": {"L1": sample_anomaly_result.timestamp.isoformat()},
            },
            "static_conformal": {
                "phase": "ready",
                "p_value": 0.25,
                "restarted_ville_threshold": 100.0,
                "tested_count": 1,
            },
        },
    )

    records = DatabaseWriter(
        db_config, session_factory=AsyncMock(), service_id="svc-static"
    ).projector._build_evidence_records([result])

    assert records == []


@pytest.mark.asyncio
async def test_missing_evidence_references_do_not_drop_alarm(
    db_config, sample_anomaly_result, mock_session_factory, monkeypatch
):
    result = replace(
        sample_anomaly_result,
        context={
            "alignment": {"aligned_vector": False, "input_timestamps": {}},
            "static_conformal": {
                "phase": "ready",
                "p_value": 0.01,
                "restarted_ville_threshold": 100.0,
                "tested_count": 1,
            },
        },
    )
    writer = DatabaseWriter(
        db_config, session_factory=mock_session_factory, service_id="svc-static"
    )
    writer._execute_upsert = AsyncMock()
    writer._execute_evidence_upsert = AsyncMock()
    writer.write_queue.append(result)

    await writer._flush_batch()

    assert len(writer._execute_upsert.await_args.args[1]) == 1
    assert writer.total_written == 1
    assert writer.total_evidence_written == 0
    assert writer.total_rejected == 0
    assert writer.write_queue == []


@pytest.mark.parametrize(
    ("write_enabled", "task_running", "expected"),
    [
        (False, None, {"status": "disabled"}),
        (True, None, {"status": "unhealthy", "reason": "writer_task_stopped"}),
        (True, True, {"status": "healthy"}),
    ],
)
def test_get_health_status_reflects_writer_task(
    db_config, write_enabled, task_running, expected
):
    db_config.db_write_enabled = write_enabled
    writer = DatabaseWriter(db_config, session_factory=AsyncMock())
    if task_running:
        writer._writer_task = MagicMock()
        writer._writer_task.done.return_value = False

    status = writer.get_health_status()

    assert {key: status.get(key) for key in expected} == expected


@pytest.mark.asyncio
async def test_test_connection_uses_session_factory(db_config):
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


@pytest.mark.asyncio
async def test_preparation_failure_retains_batch_and_writer_recovers(
    db_config, sample_anomaly_result, mock_session_factory, monkeypatch
):
    writer = DatabaseWriter(db_config, session_factory=mock_session_factory)
    project = writer.projector.prepare
    writer.write_queue.append(sample_anomaly_result)
    monkeypatch.setattr(
        writer.projector, "prepare", MagicMock(side_effect=RuntimeError("temporary"))
    )
    await writer._flush_batch()
    assert writer.write_queue == [sample_anomaly_result]
    assert writer.total_errors == 1

    monkeypatch.setattr(writer.projector, "prepare", project)
    await writer._flush_batch()
    assert writer.write_queue == []
    assert writer.total_written == 1


@pytest.mark.asyncio
async def test_session_factory_failure_retains_snapshot(
    db_config, sample_anomaly_result, monkeypatch
):
    writer = DatabaseWriter(db_config)
    writer.write_queue.append(sample_anomaly_result)
    monkeypatch.setattr(
        "off_key_mqtt_radar.database.get_radar_async_session_factory",
        MagicMock(side_effect=ValueError("database configuration unavailable")),
    )
    await writer._flush_batch()
    assert writer.write_queue == [sample_anomaly_result]
    assert writer.total_errors == 1
    assert writer.total_rejected == 0


@pytest.mark.asyncio
async def test_malformed_result_does_not_poison_valid_batch(
    db_config, sample_anomaly_result, mock_session_factory
):
    writer = DatabaseWriter(db_config, session_factory=mock_session_factory)
    malformed = replace(sample_anomaly_result, context={"static_conformal": None})
    writer.write_queue.extend([malformed, sample_anomaly_result])
    await writer._flush_batch()
    assert writer.write_queue == []
    assert writer.total_written == 1
    assert writer.total_rejected == 1


@pytest.mark.asyncio
async def test_cancellation_during_preparation_retains_snapshot(
    db_config, sample_anomaly_result, mock_session_factory, monkeypatch
):
    writer = DatabaseWriter(db_config, session_factory=mock_session_factory)
    writer.write_queue.append(sample_anomaly_result)
    monkeypatch.setattr(
        writer.projector, "prepare", MagicMock(side_effect=asyncio.CancelledError)
    )
    with pytest.raises(asyncio.CancelledError):
        await writer._flush_batch()
    assert writer.write_queue == [sample_anomaly_result]


@pytest.mark.parametrize(
    ("result", "projection"),
    [
        pytest.param(
            _scored_result(
                aligned_vector=True,
                conformal_pvalue=0.0042,
                anomaly_score=0.018,
                required_sensors=["L1", "L2"],
            ),
            {
                "telemetry_type": MULTIVARIATE_TELEMETRY_TYPE,
                "sensor_set": ["L1", "L2"],
            },
            id="multivariate-sensor-set",
        ),
        pytest.param(
            _scored_result(aligned_vector=False, anomaly_score=0.011),
            {
                "anomaly_type": "ml_conformal_static_univariate",
                "anomaly_value": 0.011,
                "telemetry_type": "sine",
                "sensor_set": ["sine"],
            },
            id="score-without-p-value",
        ),
        pytest.param(
            _scored_result(
                aligned_vector=True,
                conformal_pvalue=0.002,
                anomaly_score=0.002,
            ),
            {
                "anomaly_type": "ml_conformal_static_multivariate",
                "anomaly_value": 0.002,
                "value_type": "conformal_pvalue",
            },
            id="conformal-multivariate",
        ),
        pytest.param(
            _scored_result(
                aligned_vector=False,
                conformal_pvalue=0.003,
                anomaly_score=0.003,
            ),
            {
                "anomaly_type": "ml_conformal_static_univariate",
                "anomaly_value": 0.003,
                "value_type": "conformal_pvalue",
            },
            id="conformal-univariate",
        ),
    ],
)
def test_projected_anomaly_records_carry_detector_semantics(result, projection):
    [anomaly], _ = ResultProjector()._build_records([result])

    assert {key: anomaly[key] for key in projection} == projection
    assert {"value_type", "sensor_set"} <= set(ANOMALY_TABLE.columns.keys())


@pytest.mark.parametrize("service_id", [None, "monitor-1", "monitor-2"])
def test_build_records_scopes_alarm_and_identity_to_monitor(monkeypatch, service_id):
    result = _scored_result(
        aligned_vector=True, conformal_pvalue=0.001, anomaly_score=0.01
    )
    [anomaly], [identity] = ResultProjector(service_id or "")._build_records([result])
    assert anomaly["service_id"] == identity["service_id"] == (service_id or "")


@pytest.mark.asyncio
async def test_retry_batch_persists_value_type(monkeypatch):
    monkeypatch.setattr("off_key_mqtt_radar.database.asyncio.sleep", AsyncMock())
    session = AsyncMock()
    writer = _retrying_writer(session)
    batch_snapshot = [
        _scored_result(
            aligned_vector=False, conformal_pvalue=0.0042, anomaly_score=0.02
        )
    ]

    await writer._retry_failed_batch(batch_snapshot=batch_snapshot)

    first_insert_stmt = session.execute.await_args_list[0].args[0]
    first_row = first_insert_stmt._multi_values[0][0]
    assert first_row["value_type"] == "conformal_pvalue"


@pytest.mark.asyncio
async def test_retry_reuses_the_rows_projected_for_the_failed_flush(monkeypatch):
    monkeypatch.setattr("off_key_mqtt_radar.database.asyncio.sleep", AsyncMock())
    session = AsyncMock()
    writer = _retrying_writer(session)
    results = [
        _scored_result(aligned_vector=False, conformal_pvalue=0.001, anomaly_score=0.02)
    ]
    prepared = [writer.projector.prepare(result) for result in results]
    monkeypatch.setattr(
        writer.projector, "prepare", MagicMock(side_effect=AssertionError("re-built"))
    )

    assert await writer._retry_failed_batch(batch_snapshot=results, prepared=prepared)
    assert results == [] and prepared == []
    assert writer.total_written == 1


@pytest.mark.asyncio
async def test_retry_batch_logs_exhaustion_and_increments_errors(monkeypatch, caplog):
    monkeypatch.setattr("off_key_mqtt_radar.database.asyncio.sleep", AsyncMock())
    session = AsyncMock()
    session.execute.side_effect = RuntimeError("db down")
    writer = _retrying_writer(session)
    retry_batch = [
        _scored_result(aligned_vector=False, conformal_pvalue=0.001, anomaly_score=0.02)
    ]

    with caplog.at_level("ERROR"):
        succeeded = await writer._retry_failed_batch(batch_snapshot=retry_batch)

    assert succeeded is False
    assert writer.total_errors == 1
    assert writer.total_written == 0
    assert writer.write_queue == []
    assert any(
        "event=radar.db_retry_exhausted" in rec.message for rec in caplog.records
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("chunk_outcomes", "raises"),
    [
        pytest.param(
            [None] + [RuntimeError("second chunk failed")] * 3, None, id="fail"
        ),
        pytest.param(
            [None, asyncio.CancelledError], asyncio.CancelledError, id="cancel"
        ),
    ],
)
async def test_retry_only_requeues_uncommitted_chunks(
    monkeypatch, chunk_outcomes, raises
):
    monkeypatch.setattr("off_key_mqtt_radar.database.asyncio.sleep", AsyncMock())
    session = AsyncMock()
    writer = _retrying_writer(session)
    writer._execute_upsert = AsyncMock(
        side_effect=[RuntimeError("initial write failed"), *chunk_outcomes]
    )
    writer._execute_evidence_upsert = AsyncMock()
    start = datetime.now(UTC)
    results = [
        replace(
            _scored_result(
                aligned_vector=False, conformal_pvalue=0.001, anomaly_score=0.02
            ),
            timestamp=start + timedelta(seconds=index),
        )
        for index in range(11)
    ]
    writer.write_queue.extend(results)

    if raises:
        with pytest.raises(raises):
            await writer._flush_batch()
    else:
        await writer._flush_batch()

    assert writer.write_queue == results[10:]
    assert writer.total_written == 10
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("write_error", "retry_error", "raises", "errors"),
    [
        (RuntimeError("flush failed"), RuntimeError("retry crashed"), None, 2),
        (
            RuntimeError("flush failed"),
            asyncio.CancelledError,
            asyncio.CancelledError,
            1,
        ),
        (asyncio.CancelledError, None, asyncio.CancelledError, 0),
    ],
)
async def test_flush_batch_requeues_snapshot_when_writing_or_retrying_fails(
    write_error, retry_error, raises, errors
):
    writer = _retrying_writer()
    anomaly = _scored_result(
        aligned_vector=False, conformal_pvalue=0.002, anomaly_score=0.02
    )
    writer.write_queue = [anomaly]
    writer._execute_upsert = AsyncMock(side_effect=write_error)
    writer._retry_failed_batch = AsyncMock(side_effect=retry_error)

    if raises:
        with pytest.raises(raises):
            await writer._flush_batch()
    else:
        await writer._flush_batch()

    assert writer.write_queue == [anomaly]
    assert writer.total_errors == errors
