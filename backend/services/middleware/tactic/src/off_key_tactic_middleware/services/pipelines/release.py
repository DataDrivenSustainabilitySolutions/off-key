"""Explicit saved-configuration normalization and linked release runs."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

from off_key_core.db.models import PipelineRun
from off_key_core.models import ABERRANT_VERSION
from off_key_core.models.pipelines import (
    compile_pipeline,
    derive_monitoring_config,
    execution_fingerprint,
)
from off_key_core.schemas.pipelines import PipelineExecutionConfig
from off_key_core.schemas.radar import FormMonitorConfig, RadarStartConfig
from sqlalchemy import select

from .preflight import PipelinePreflight
from .runs import ensure_predecessor_run


def _reviewed_saved_launch(value: dict) -> dict:
    """A copy whose adaptive model version this release can run."""
    value = deepcopy(value)
    monitoring = value.get("monitoring", {})
    if monitoring.get("strategy") == "adaptive_stream":
        previous = monitoring.get("aberrant_version", ABERRANT_VERSION)
        if previous not in {"1.1.0", "1.2.0", ABERRANT_VERSION}:
            raise ValueError(
                f"No reviewed release normalization for Aberrant {previous}"
            )
        monitoring["aberrant_version"] = ABERRANT_VERSION
    return value


def is_saved_form_monitor(value: dict) -> bool:
    """Launches saved before every monitor ran as a pipeline carry none."""
    return not value.get("pipeline")


def saved_form_monitor(value: dict) -> FormMonitorConfig:
    """Read a launch saved by the setup forms; historical records stay as saved."""
    value = _reviewed_saved_launch(value)
    for key in ("pipeline", "runtime_image"):
        if value.get(key) is None:
            value.pop(key, None)
    return FormMonitorConfig.model_validate(value)


def normalize_saved_launch(value: dict) -> RadarStartConfig:
    """A release restarts learning; historical records remain unmodified."""
    if is_saved_form_monitor(value):
        raise ValueError("Convert the saved form monitor to a pipeline first")
    value = _reviewed_saved_launch(value)
    execution = PipelineExecutionConfig.model_validate(value["pipeline"])
    definition = compile_pipeline(execution.definition).definition
    execution = execution.model_copy(
        update={
            "definition": definition,
            "fingerprint": execution_fingerprint(definition, execution.bindings),
        }
    )
    value["pipeline"] = execution.model_dump(mode="json")
    value["monitoring"] = derive_monitoring_config(definition).model_dump(mode="json")
    # The target release image must be resolved again, never the predecessor image.
    value["runtime_image"] = None
    return RadarStartConfig.model_validate(value)


async def _previous_run(session, monitor, config):
    original = monitor.get("previous_config") or monitor["config"]
    execution = original.get("pipeline")
    return await ensure_predecessor_run(
        session,
        service_id=monitor["previous_id"],
        launch_config=original,
        execution=execution,
        revision_id=execution["revision_id"] if execution else None,
        created_at=datetime.now(UTC),
    )


async def prepare_release_monitors(session, operation, workloads):
    snapshots = list(operation.monitors)
    for index, monitor in enumerate(snapshots):
        if monitor["config"] is None:
            continue
        config = normalize_saved_launch(monitor["config"])
        if not monitor.get("previous_run_id"):
            previous = await _previous_run(session, monitor, config)
            monitor = monitor | {"previous_run_id": previous.id}
        monitor = await _prepare_graph_run(session, monitor, config, workloads)
        snapshots[index] = monitor
        operation.monitors = list(snapshots)
        await session.commit()
        if not monitor.get("preflight"):
            config = RadarStartConfig.model_validate(monitor["config"])
            pipeline, image = config.pipeline, config.runtime_image
            if image is None:
                # _prepare_graph_run always writes it into the stored config.
                raise RuntimeError("Prepared pipeline release lost its image")
            report = await PipelinePreflight(workloads).run(
                f"release-{pipeline.run_id}", pipeline, image
            )
            snapshots[index] = monitor | {"preflight": report}
            operation.monitors = list(snapshots)
            await session.commit()


async def _prepare_graph_run(session, monitor, config, workloads):
    if monitor.get("replacement_run_id"):
        return monitor
    service_id, run_id = str(uuid4()), str(uuid4())
    execution = config.pipeline.model_copy(update={"run_id": run_id})
    image = await PipelinePreflight(workloads).resolve_image()
    config = config.model_copy(
        update={
            "container_name": f"pipeline-{service_id}",
            "pipeline": execution,
            "runtime_image": image,
        }
    )
    previous = await session.get(PipelineRun, monitor["previous_run_id"])
    session.add(
        PipelineRun(
            id=run_id,
            service_id=service_id,
            revision_id=execution.revision_id,
            predecessor_run_id=previous.id,
            execution=execution.model_dump(mode="json"),
            launch_config=config.model_dump(mode="json"),
            layout=previous.layout,
            # A converted form monitor brings the metadata of its new bindings.
            binding_metadata=monitor.get("binding_metadata")
            or previous.binding_metadata,
            status="reserved",
            created_at=datetime.now(UTC),
        )
    )
    return monitor | {
        "replacement_service_id": service_id,
        "replacement_run_id": run_id,
        "config": config.model_dump(mode="json"),
    }


async def record_release_run(session, monitor, service):
    run = await session.scalar(
        select(PipelineRun)
        .where(PipelineRun.service_id == service.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if run is None:
        raise RuntimeError("The prepared release run is missing")
    if run.ended_at is None:
        run.status = "starting"
