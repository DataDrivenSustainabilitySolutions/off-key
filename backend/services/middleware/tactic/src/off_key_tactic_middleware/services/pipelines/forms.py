"""Monitors configured with the setup forms run as pipelines."""

from uuid import uuid4

from off_key_core.db.collection_runtime import read_collection_runtime
from off_key_core.models.pipelines import form_inputs
from off_key_core.schemas.pipelines import (
    PipelineActivationView,
    PipelineApplyRequest,
    PipelineBindingMetadata,
)
from off_key_core.schemas.radar import FormMonitorConfig, RadarStartConfig
from pydantic import ValidationError as PydanticValidationError

from ...domain import DomainError, ValidationError
from .activation import PipelineActivations
from .library import legacy_definition
from .release import saved_form_monitor


async def _form_request(session, config: FormMonitorConfig) -> PipelineApplyRequest:
    """The pipeline apply request equivalent to a form configuration."""
    try:
        definition = legacy_definition(config)
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
    return PipelineApplyRequest(
        definition=definition,
        bindings={
            f"input_{index + 1}": readings[topic]
            for index, (_, topic) in enumerate(inputs)
        },
        display_name=(config.display_name or config.container_name)[:120],
        idempotency_key=f"form-{uuid4()}",
    )


async def start_form_monitor(
    session, config: FormMonitorConfig, workloads=None
) -> PipelineActivationView:
    """Convert a form launch into its equivalent graph and activate it."""
    request = await _form_request(session, config)
    return await PipelineActivations(session, workloads).apply_form(
        request, config.performance_config
    )


class UnconvertibleFormMonitor(ValueError):
    """A saved form monitor whose configuration or readings no longer exist."""


async def convert_saved_form_monitor(
    session, launch: dict
) -> tuple[RadarStartConfig, PipelineBindingMetadata]:
    """The pipeline launch that replaces a monitor saved by the setup forms.

    A release restarts the monitor from this launch, so it learns again.
    """
    try:
        config = saved_form_monitor(launch)
        request = await _form_request(session, config)
        return await PipelineActivations(session).form_launch(request, config)
    except (ValidationError, PydanticValidationError) as exc:
        raise UnconvertibleFormMonitor(str(exc)) from exc
    except DomainError as exc:
        # For example unapplied collection; the release waits instead.
        raise ValueError(str(exc)) from exc
