"""Activations end, refuse a cancel that strands a replacement, and keep stars."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from off_key_core.db.models import (
    MemberFavorite,
    MonitoringService,
    PipelineActivation,
    PipelineRun,
    User,
)
from off_key_core.schemas.pipelines import PipelineActivationRequest
from off_key_tactic_middleware.domain import ConflictError
from off_key_tactic_middleware.services.pipelines.activation import (
    PipelineActivations,
    carry_monitor_favorites,
)
from off_key_tactic_middleware.services.pipelines.preflight import PipelinePreflight
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tests.support.pipeline_database import published_design

pytestmark = pytest.mark.radar_integration


async def _submit(session, key):
    _, revision = await published_design(session)
    return await PipelineActivations(session).submit(
        PipelineActivationRequest(
            revision_id=revision.id,
            bindings={"value": "current"},
            display_name="Guarded",
            idempotency_key=key,
        )
    )


@pytest.mark.asyncio
async def test_a_phase_that_outlasts_its_budget_ends_as_failed(
    pipeline_database, monkeypatch
):
    workloads = SimpleNamespace(
        remove_intent=AsyncMock(return_value=True), async_docker=None
    )
    monkeypatch.setattr(PipelinePreflight, "remove_for", AsyncMock())
    async with pipeline_database() as session:
        activation = await _submit(session, "phase-budget")
        row = await session.get(PipelineActivation, activation.id)
        assert row.phase_entered_at is not None
        row.phase = "retiring"
        row.phase_entered_at = datetime.now(UTC) - timedelta(hours=1)
        await session.commit()

        controller = PipelineActivations(session, workloads=workloads)
        await controller.advance(activation.id)
        await controller.advance(activation.id)

        row = await session.get(
            PipelineActivation, activation.id, populate_existing=True
        )
        assert row.phase == "failed"
        assert "within 900 seconds" in row.error
        run = await session.get(PipelineRun, row.run_id, populate_existing=True)
        assert run.status == "failed" and run.ended_at is not None


@pytest.mark.asyncio
async def test_a_fresh_phase_keeps_retrying_inside_its_budget(
    pipeline_database, monkeypatch
):
    async def outage(*_args, **_kwargs):
        raise RuntimeError("Docker is unreachable")

    monkeypatch.setattr(PipelinePreflight, "resolve_image", outage)
    async with pipeline_database() as session:
        activation = await _submit(session, "phase-retry")
        controller = PipelineActivations(
            session, workloads=SimpleNamespace(async_docker=None)
        )
        await controller.advance(activation.id)
        row = await session.get(
            PipelineActivation, activation.id, populate_existing=True
        )
        assert row.phase == "preflighting"
        assert not row.cancel_requested
        assert "Docker is unreachable" in row.error


@pytest.mark.asyncio
async def test_cancel_is_refused_once_the_predecessor_is_retiring(pipeline_database):
    async with pipeline_database() as session:
        activation = await _submit(session, "retired-cancel")
        row = await session.get(PipelineActivation, activation.id)
        row.phase = "starting"
        row.retirement_started = True
        await session.commit()

        with pytest.raises(ConflictError, match="nothing running"):
            await PipelineActivations(session).cancel(activation.id)
        row = await session.get(
            PipelineActivation, activation.id, populate_existing=True
        )
        assert not row.cancel_requested
        view = await PipelineActivations(session).get(activation.id)
        assert view.retirement_started


@pytest.mark.asyncio
async def test_cancelling_hands_an_unconfirmed_delete_to_reconciliation(
    pipeline_database, monkeypatch
):
    monkeypatch.setattr(PipelinePreflight, "remove_for", AsyncMock())
    async with pipeline_database() as session:
        activation = await _submit(session, "cancel-handoff")
        session.add(
            MonitoringService(
                id=activation.service_id,
                container_id="workload",
                container_name="cancel-handoff",
                mqtt_topic=["fixture/current"],
                status=True,
                desired_state="running",
                config_fingerprint="fingerprint",
            )
        )
        row = await session.get(PipelineActivation, activation.id)
        row.phase = "cancelling"
        row.cancel_requested = True
        await session.commit()

        # Docker cannot confirm removal; the delete intent is still durable.
        workloads = SimpleNamespace(
            remove_intent=AsyncMock(side_effect=RuntimeError("Docker outage")),
            async_docker=None,
        )
        await PipelineActivations(session, workloads=workloads).advance(activation.id)

        row = await session.get(
            PipelineActivation, activation.id, populate_existing=True
        )
        assert row.phase == "cancelled"
        service = await session.get(
            MonitoringService, activation.service_id, populate_existing=True
        )
        assert service.desired_state == "deleted"
        assert service.stop_requested_at is not None


@pytest.mark.asyncio
async def test_monitor_favorites_follow_the_replacement(pipeline_database):
    async with pipeline_database() as session:
        starred, both = (
            User(email=f"{name}@example.org", hashed_password="!", is_verified=True)
            for name in ("starred", "both")
        )
        session.add_all([starred, both])
        await session.flush()
        session.add_all(
            [
                MemberFavorite(user_id=starred.id, kind="monitor", item_id="old"),
                MemberFavorite(user_id=both.id, kind="monitor", item_id="old"),
                MemberFavorite(user_id=both.id, kind="monitor", item_id="new"),
                MemberFavorite(user_id=both.id, kind="reading", item_id="old"),
            ]
        )
        await session.commit()

        await carry_monitor_favorites(session, "old", "new")
        await session.commit()

        rows = (
            await session.execute(
                select(
                    MemberFavorite.user_id, MemberFavorite.kind, MemberFavorite.item_id
                ).order_by(MemberFavorite.user_id, MemberFavorite.kind)
            )
        ).all()
        assert sorted(rows) == sorted(
            [
                (starred.id, "monitor", "new"),
                (both.id, "monitor", "new"),
                (both.id, "reading", "old"),
            ]
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "column", "value"),
    [
        (MonitoringService, "desired_state", "paused"),
        (PipelineRun, "status", "unknown"),
        (PipelineActivation, "phase", "retired"),
    ],
)
async def test_lifecycle_columns_reject_unknown_states(
    pipeline_database, model, column, value
):
    async with pipeline_database() as session:
        activation = await _submit(session, f"check-{column}-{value}")
        if model is MonitoringService:
            session.add(
                MonitoringService(
                    id=activation.service_id,
                    container_name="checked",
                    mqtt_topic=[],
                    desired_state="running",
                )
            )
            await session.commit()
            identifier = activation.service_id
        else:
            identifier = activation.run_id if model is PipelineRun else activation.id
        row = await session.get(model, identifier)
        setattr(row, column, value)
        with pytest.raises(IntegrityError):
            await session.commit()
