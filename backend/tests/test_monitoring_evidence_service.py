from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from off_key_tactic_middleware.repositories.data import MonitoringEvidenceRepository
from off_key_tactic_middleware.services.data.monitoring_evidence import (
    MonitoringEvidenceService,
)


@pytest.mark.asyncio
async def test_forward_evidence_query_pages_in_ingestion_order():
    now = datetime.now(UTC)
    session = AsyncMock()
    result = MagicMock()
    result.all.return_value = []
    session.execute.return_value = result

    await MonitoringEvidenceRepository(session).list_chart_by_charger(
        charger_id="charger-1",
        after_created=now,
        after_timestamp=now - timedelta(seconds=1),
        after_service_id="svc-static",
        after_sequence_number=1,
        limit=2000,
    )

    query = str(session.execute.await_args.args[0])
    assert "monitoring_evidence.created >" in query
    assert "ORDER BY monitoring_evidence.created ASC" in query


@pytest.mark.asyncio
async def test_forward_evidence_query_rejects_incomplete_cursor():
    now = datetime.now(UTC)

    with pytest.raises(ValueError, match="after_service_id"):
        await MonitoringEvidenceRepository(AsyncMock()).list_chart_by_charger(
            charger_id="charger-1",
            after_created=now,
            after_timestamp=now,
            after_service_id=None,
            after_sequence_number=1,
            limit=2000,
        )


def _evidence(sequence_number: int, timestamp: datetime):
    return SimpleNamespace(
        service_id="svc-static",
        timestamp=timestamp,
        sequence_number=sequence_number,
        charger_id="charger-1",
        sensor_set=["L1", "L2", "L3"],
        p_value=0.2,
        e_value=1.2,
        e_value_is_infinite=False,
        log_e_value=0.18,
        restarted_martingale=4.0,
        restarted_martingale_is_infinite=False,
        log_restarted_martingale=1.39,
        tracker_results=[],
        threshold=100.0,
        alarm=False,
        created=timestamp + timedelta(milliseconds=1),
    )


@pytest.mark.asyncio
async def test_evidence_service_returns_chart_points_in_time_order():
    now = datetime.now(UTC)
    repository = AsyncMock()
    repository.list_by_charger.return_value = [
        _evidence(2, now),
        _evidence(1, now - timedelta(seconds=1)),
    ]
    service = MonitoringEvidenceService(repository)

    rows = await service.list_evidence(
        charger_id="charger-1", telemetry_type="L2", limit=50
    )

    repository.list_by_charger.assert_awaited_once_with(
        charger_id="charger-1", telemetry_type="L2", limit=50
    )
    assert [row["sequence_number"] for row in rows] == [1, 2]
    assert rows[0]["sensor_set"] == ["L1", "L2", "L3"]
    assert rows[0]["threshold"] == 100.0


@pytest.mark.asyncio
async def test_chart_evidence_service_uses_compact_cursor_projection():
    now = datetime.now(UTC)
    repository = AsyncMock()
    repository.list_chart_by_charger.return_value = [_evidence(2, now)]
    service = MonitoringEvidenceService(repository)

    rows = await service.list_chart_evidence(
        charger_id="charger-1",
        after_created=now - timedelta(seconds=1),
        after_timestamp=now - timedelta(seconds=1),
        after_service_id="svc-static",
        after_sequence_number=1,
        limit=50,
    )

    repository.list_chart_by_charger.assert_awaited_once_with(
        charger_id="charger-1",
        after_created=now - timedelta(seconds=1),
        after_timestamp=now - timedelta(seconds=1),
        after_service_id="svc-static",
        after_sequence_number=1,
        limit=50,
    )
    assert rows == [
        {
            "service_id": "svc-static",
            "timestamp": now,
            "sequence_number": 2,
            "sensor_set": ["L1", "L2", "L3"],
            "strategy": "static_baseline",
            "model_type": None,
            "anomaly_score": None,
            "restarted_martingale": 4.0,
            "tracker_results": [],
            "threshold": 100.0,
            "alarm": False,
            "created": now + timedelta(milliseconds=1),
        }
    ]
