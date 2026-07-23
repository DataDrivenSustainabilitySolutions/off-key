from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from off_key_tactic_middleware.services.data.monitoring_evidence import (
    MonitoringEvidenceService,
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
        threshold=100.0,
        alarm=False,
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
