"""Static releases check existing monitors without replacing or mutating them."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from off_key_tactic_middleware import deployment


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault", [None, "ended", "failed", "inactive", "stale", "degraded", "missing"]
)
async def test_static_verification_requires_live_healthy_existing_monitors(fault):
    run = SimpleNamespace(ended_at=None, status="running")
    service = SimpleNamespace(
        status=True,
        operational_updated_at=datetime.now(UTC),
        operational_stage="running",
    )
    if fault == "ended":
        run.ended_at = datetime.now(UTC)
    elif fault == "failed":
        run.status = "failed"
    elif fault == "inactive":
        service.status = False
    elif fault == "stale":
        service.operational_updated_at -= timedelta(hours=1)
    elif fault == "degraded":
        service.operational_stage = "degraded"
    result = MagicMock()
    result.all.return_value = ["existing-monitor"]
    session = SimpleNamespace(
        scalars=AsyncMock(return_value=result),
        scalar=AsyncMock(return_value=None if fault == "missing" else run),
        get=AsyncMock(return_value=service),
        commit=AsyncMock(),
        delete=AsyncMock(),
    )
    if fault:
        with pytest.raises(ValueError, match="healthy runtime"):
            await deployment.verify_active(session)
    else:
        assert await deployment.verify_active(session) == {"verified": 1}
    session.commit.assert_not_called()
    session.delete.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fault",
    [
        None,
        "wrong-release",
        "wrong-phase",
        "stopped",
        "replaced",
        "changed-worker",
        "unhealthy",
    ],
)
async def test_static_completion_requires_its_own_reservation_and_original_workers(
    monkeypatch, fault
):
    monkeypatch.setattr(deployment, "lock_collection_configuration", AsyncMock())
    monitor = {
        "previous_id": "monitor",
        "workload_id": "original-worker",
        "active": True,
        "stopped": False,
        "replacement_id": None,
    }
    operation = SimpleNamespace(
        revision="a" * 40, phase="quiescing", monitors=[monitor]
    )
    service = SimpleNamespace(
        container_id="original-worker",
        stop_requested_at=None,
        status=True,
        operational_updated_at=datetime.now(UTC),
        operational_stage="waiting_for_data",
    )
    if fault == "wrong-release":
        operation.revision = "b" * 40
    elif fault == "wrong-phase":
        operation.phase = "stopped"
    elif fault == "stopped":
        monitor["stopped"] = True
    elif fault == "replaced":
        monitor["replacement_id"] = "new-monitor"
    elif fault == "changed-worker":
        service.container_id = "new-worker"
    elif fault == "unhealthy":
        service.operational_updated_at -= timedelta(hours=1)
    session = SimpleNamespace(
        get=AsyncMock(
            side_effect=lambda model, *args, **kwargs: (
                operation if model is deployment.DeploymentMaintenance else service
            )
        ),
        scalar=AsyncMock(return_value=SimpleNamespace(ended_at=None, status="running")),
        commit=AsyncMock(),
    )
    if fault:
        with pytest.raises(ValueError):
            await deployment.finish_static(session, "a" * 40)
        session.commit.assert_not_called()
    else:
        assert await deployment.finish_static(session, "a" * 40) == {
            "phase": "complete"
        }
        session.commit.assert_awaited_once()
        assert service.container_id == "original-worker"
