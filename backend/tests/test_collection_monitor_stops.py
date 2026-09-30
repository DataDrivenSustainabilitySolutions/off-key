"""Exercise durable stop progress using real, independent SQL transactions."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from off_key_core.db.models import MonitoringService
from off_key_core.schemas.collection import (
    AmbiboxCatalog,
    CatalogChange,
    CatalogPreview,
)
from off_key_core.schemas.radar import RadarOperationalStatus
from off_key_tactic_middleware.domain import InfrastructureError
from off_key_tactic_middleware.services import collection
from off_key_tactic_middleware.services.radar_status import derive_operational_status
from off_key_tactic_middleware.services.reconciliation import (
    RadarStatusReconciliationService,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def stops(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'stops.db'}")
    MonitoringService.__table__.create(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as session:
        session.add_all(
            [
                MonitoringService(
                    id=str(index),
                    container_id=f"ctr-{index}",
                    container_name=f"monitor-{index}",
                    status=True,
                    mqtt_topic=[f"telemetry/{index}"],
                    operational_stage="operational",
                    operational_status={"stage": "operational"},
                )
                for index in range(2)
            ]
        )

    class AsyncTransaction:
        """Adapt synchronous test SQL without mocking commits or rollbacks."""

        @asynccontextmanager
        async def begin(self):
            with sessions.begin() as session:
                yield MagicMock(
                    execute=AsyncMock(side_effect=session.execute),
                    get=AsyncMock(side_effect=session.get),
                )

    monkeypatch.setattr(collection, "get_async_session_local", AsyncTransaction)
    workloads = MagicMock(remove=AsyncMock(return_value=True))
    monkeypatch.setattr(collection, "get_async_docker", MagicMock())
    monkeypatch.setattr(collection, "RadarWorkloadManager", lambda _: workloads)
    try:
        yield sessions, workloads
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_partial_pause_survives_rollback_and_reconciliation_finishes(stops):
    sessions, workloads = stops
    workloads.remove.side_effect = [True, RuntimeError("Docker unavailable")]
    service = collection.CollectionService(AsyncMock(expire_all=MagicMock()))

    with pytest.raises(InfrastructureError, match="retried automatically"):
        await service._pause_monitors([{"id": "0"}, {"id": "1"}])

    with sessions() as session:
        stopped, pending = (
            session.get(MonitoringService, "0"),
            session.get(MonitoringService, "1"),
        )
        assert not stopped.status and stopped.stop_requested_at is None
        assert (
            RadarOperationalStatus.model_validate(
                derive_operational_status(stopped)
            ).stage
            == "stopped"
        )
        assert pending.status and pending.stop_requested_at is not None

    reconciler = object.__new__(RadarStatusReconciliationService)
    reconciler._get_docker_status = AsyncMock(return_value="running")
    reconciler._remove_workload_if_present = AsyncMock(return_value=False)
    with sessions.begin() as session:
        pending = session.get(MonitoringService, "1")
        await reconciler._reconcile_service(AsyncMock(), pending)
    reconciler._get_docker_status.assert_not_awaited()
    reconciler._remove_workload_if_present.assert_awaited_once_with("ctr-1")
    with sessions() as session:
        pending = session.get(MonitoringService, "1")
        assert not pending.status and pending.stop_requested_at is None


@pytest.mark.asyncio
async def test_catalog_failure_does_not_undo_successful_stops(stops, monkeypatch):
    sessions, workloads = stops
    monkeypatch.setattr(collection, "lock_collection_configuration", AsyncMock())
    service = collection.CollectionService(AsyncMock(expire_all=MagicMock()))
    service.preview = AsyncMock(
        return_value=CatalogPreview(
            revision=0,
            catalog=AmbiboxCatalog(),
            chargers=0,
            selected_sensors=0,
            sampled_rows_per_day_ceiling=0,
            original_rate_sensors=0,
            affected_monitors=[
                {"id": "0", "name": "first"},
                {"id": "1", "name": "second"},
            ],
        )
    )
    service._update_bindings = AsyncMock(
        side_effect=RuntimeError("catalog write failed")
    )

    with pytest.raises(RuntimeError, match="catalog write failed"):
        await service.apply(
            CatalogChange(
                expected_revision=0,
                catalog=AmbiboxCatalog(),
                pause_affected_monitors=True,
            ),
            actor="test",
        )
    assert workloads.remove.await_count == 2
    with sessions() as session:
        assert all(
            not session.get(MonitoringService, str(index)).status for index in range(2)
        )


@pytest.mark.asyncio
async def test_intent_commit_failure_prevents_workload_removal(stops, monkeypatch):
    _, workloads = stops
    sessions = collection.get_async_session_local()
    original_begin = sessions.begin

    @asynccontextmanager
    async def fail_commit():
        async with original_begin() as session:
            yield session
            raise RuntimeError("intent commit failed")

    sessions.begin = fail_commit
    monkeypatch.setattr(collection, "get_async_session_local", lambda: sessions)
    with pytest.raises(RuntimeError, match="intent commit failed"):
        await collection.CollectionService(AsyncMock())._pause_monitors([{"id": "0"}])
    workloads.remove.assert_not_awaited()
