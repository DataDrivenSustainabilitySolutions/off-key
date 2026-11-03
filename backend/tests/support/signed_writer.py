"""A real signed-state RADAR writer bound to one activated pipeline run."""

from datetime import UTC, datetime

import pytest_asyncio
from off_key_core.db.models import MonitoringService, PipelineRun
from off_key_core.schemas.pipelines import (
    PipelineActivationRequest,
    PipelineExecutionConfig,
)
from off_key_mqtt_radar import database as radar_database
from off_key_mqtt_radar.config.config import MQTTRadarConfig
from off_key_mqtt_radar.config.runtime import clear_radar_runtime_settings_cache
from off_key_mqtt_radar.database import DatabaseWriter
from off_key_mqtt_radar.detector import StaticConformalDetectionService
from off_key_mqtt_radar.runtime_checkpoint import (
    CoverageCheckpoint,
    ProcessorCheckpoint,
    RuntimeCheckpoint,
    RuntimeCheckpointCodec,
)
from off_key_tactic_middleware.services.pipelines.activation import PipelineActivations

from tests.support.pipeline_database import published_design


@pytest_asyncio.fixture
async def signed_graph_writer(pipeline_database, monkeypatch):
    monkeypatch.setattr(
        radar_database, "_radar_async_session_factory", pipeline_database
    )
    async with pipeline_database() as session:
        _, revision = await published_design(session)
        activation = await PipelineActivations(session).submit(
            PipelineActivationRequest(
                revision_id=revision.id,
                bindings={"value": "current"},
                display_name="Failure status race",
                idempotency_key="failure-status-race",
            )
        )
        run = await session.get(PipelineRun, activation.run_id)
        run.status = "running"
        execution = PipelineExecutionConfig.model_validate(run.execution)
        session.add(
            MonitoringService(
                id=activation.service_id,
                container_name=run.launch_config["container_name"],
                mqtt_topic=run.launch_config["mqtt_topics"],
                status=True,
                desired_state="running",
                lifecycle_version=1,
                operational_stage="operational",
                operational_updated_at=datetime.now(UTC),
                launch_config=run.launch_config,
            )
        )
        await session.commit()
    monkeypatch.setenv("SERVICE_ID", activation.service_id)
    clear_radar_runtime_settings_cache()
    config = MQTTRadarConfig(pipeline=execution)
    detector = StaticConformalDetectionService(config)
    writer = DatabaseWriter(
        config, session_factory=pipeline_database, managed_checkpoints=True
    )
    try:
        codec = RuntimeCheckpointCodec(
            activation.service_id, config, b"disposable-failure-status-secret"
        )
        snapshot = codec.encode(
            RuntimeCheckpoint(
                detector=detector.export_checkpoint(),
                processor=ProcessorCheckpoint(),
                coverage=CoverageCheckpoint(data={}),
            )
        )
        assert await writer.load_checkpoint(activation.service_id) is None
        await writer.commit_checkpoint(snapshot)
        yield writer, pipeline_database, activation, snapshot, codec
    finally:
        detector.shutdown()
        clear_radar_runtime_settings_cache()


def healthy_metrics():
    return {
        "service_status": "healthy",
        "operational_status": {
            "stage": "operational",
            "updated_at": datetime.now(UTC),
            "pipeline_state": {"nodes": {"detector": {"state": "ready"}}},
        },
    }
