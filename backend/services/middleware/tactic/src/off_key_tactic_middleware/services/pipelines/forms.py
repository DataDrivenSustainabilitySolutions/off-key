"""Monitors configured with the setup forms run as pipelines."""

from uuid import uuid4

from off_key_core.db.collection_runtime import read_collection_runtime
from off_key_core.models.pipelines import form_inputs
from off_key_core.schemas.pipelines import PipelineActivationView, PipelineApplyRequest
from off_key_core.schemas.radar import RadarStartConfig

from ...domain import ValidationError
from .activation import PipelineActivations
from .library import legacy_definition


async def start_form_monitor(
    session, config: RadarStartConfig, workloads=None
) -> PipelineActivationView:
    """Convert a form launch into its equivalent graph and activate it."""
    if config.pipeline is not None:
        raise ValidationError("Apply pipeline designs through /pipelines/apply")
    try:
        definition = legacy_definition(config.model_dump(mode="json"))
        inputs = form_inputs(config)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    snapshot = await read_collection_runtime(session)
    readings = {
        stream.accepted_topic: stream.definition.id
        for stream in snapshot.catalog.streams(selected_only=True)
        if stream.value_type == "number"
    }
    missing = [topic for _, topic in inputs if topic not in readings]
    if missing:
        raise ValidationError(
            f"Select these topics as numeric readings first: {', '.join(missing)}"
        )
    request = PipelineApplyRequest(
        definition=definition,
        bindings={
            f"input_{index + 1}": readings[topic]
            for index, (_, topic) in enumerate(inputs)
        },
        display_name=(config.display_name or config.container_name)[:120],
        idempotency_key=f"form-{uuid4()}",
    )
    return await PipelineActivations(session, workloads).apply_form(
        request, config.performance_config
    )
