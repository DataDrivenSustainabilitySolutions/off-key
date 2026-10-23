"""Real durable activation scheduling with controlled remote Docker I/O."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import docker
import pytest
from off_key_core.db.models import MonitoringService, PipelineActivation
from off_key_core.models.pipelines import pipeline_catalog_id
from off_key_core.schemas.pipelines import PipelineActivationRequest
from off_key_tactic_middleware.config.config import clear_tactic_settings_caches
from off_key_tactic_middleware.services.pipelines.activation import PipelineActivations
from off_key_tactic_middleware.services.pipelines.preflight import PipelinePreflight
from off_key_tactic_middleware.services.pipelines.preflight_cleanup import (
    PreflightOrphans,
)
from off_key_tactic_middleware.services.pipelines.supervisor import (
    PipelineActivationSupervisor,
)

from tests.support.pipeline_database import published_design


@pytest.mark.asyncio
async def test_slow_preflight_and_cleanup_do_not_delay_heartbeat_or_queued_cancel(
    pipeline_database, monkeypatch
):
    monkeypatch.setenv("TACTIC_PIPELINE_MAX_CONCURRENT_PREFLIGHTS", "1")
    clear_tactic_settings_caches()
    preflight_started = asyncio.Event()
    release_preflight = asyncio.Event()
    cleanup_started = asyncio.Event()
    release_cleanup = asyncio.Event()

    async def remote_preflight(_self, *_args):
        preflight_started.set()
        await release_preflight.wait()
        return {"ok": True, "catalog_id": pipeline_catalog_id()}

    async def remote_cleanup(_self):
        cleanup_started.set()
        await release_cleanup.wait()

    monkeypatch.setattr(PipelinePreflight, "run", remote_preflight)
    monkeypatch.setattr(PreflightOrphans, "sweep", remote_cleanup)
    workloads = SimpleNamespace(
        async_docker=SimpleNamespace(
            client=SimpleNamespace(services=SimpleNamespace(get=None)),
            run=AsyncMock(side_effect=docker.errors.NotFound("no preflight")),
        ),
        remove_intent=AsyncMock(),
    )
    async with pipeline_database() as session:
        _, revision = await published_design(session)
        operations = []
        for reading in ("current", "temperature", "other_current"):
            operation = await PipelineActivations(session).submit(
                PipelineActivationRequest(
                    revision_id=revision.id,
                    bindings={"value": reading},
                    display_name=reading,
                    idempotency_key="supervision-" + reading,
                )
            )
            operations.append(operation)
            row = await session.get(PipelineActivation, operation.id)
            row.image_digest = "sha256:" + "a" * 64
        healthy = await session.get(PipelineActivation, operations[1].id)
        healthy.phase = "awaiting_heartbeat"
        healthy.heartbeat_deadline = datetime.now(UTC) + timedelta(seconds=10)
        session.add(
            MonitoringService(
                id=healthy.service_id,
                container_name=healthy.launch_config["container_name"],
                mqtt_topic=healthy.launch_config["mqtt_topics"],
                launch_config=healthy.launch_config,
                status=True,
                desired_state="running",
                lifecycle_version=1,
                operational_stage="starting",
                operational_updated_at=None,
            )
        )
        await session.commit()

    supervisor = PipelineActivationSupervisor(workloads, sessions=pipeline_database)
    await supervisor.start()
    try:
        async with asyncio.timeout(5):
            await preflight_started.wait()
            await cleanup_started.wait()
            async with pipeline_database.begin() as session:
                queued = await session.get(PipelineActivation, operations[2].id)
                assert queued.controller_token is None
                assert queued.phase == "requested"
                queued.cancel_requested = True
                service = await session.get(MonitoringService, healthy.service_id)
                service.operational_stage = "operational"
                service.operational_updated_at = datetime.now(UTC)
            while True:
                async with pipeline_database() as session:
                    verified = await session.get(PipelineActivation, operations[1].id)
                    cancelled = await session.get(PipelineActivation, operations[2].id)
                    if verified.phase == "succeeded" and cancelled.phase == "cancelled":
                        break
                await asyncio.sleep(0.02)
            assert not release_preflight.is_set()
            assert supervisor.active["preflight"] == {operations[0].id}
    finally:
        release_preflight.set()
        release_cleanup.set()
        await supervisor.stop()
        clear_tactic_settings_caches()
