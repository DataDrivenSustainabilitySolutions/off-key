"""Monitors configured with the setup forms run as pipelines."""

from uuid import uuid4

from aberration_core.db.collection_runtime import read_collection_runtime
from aberration_core.models.pipelines import form_inputs
from aberration_core.schemas.pipelines import (
    PipelineActivationView,
    PipelineApplyRequest,
    PipelineBindingMetadata,
)
from aberration_core.schemas.radar import (
    FormMonitorConfig,
    MonitorSetup,
    RadarStartConfig,
)
from pydantic import ValidationError as PydanticValidationError

from ...domain import DomainError, ValidationError
from .activation import PipelineActivations
from .library import legacy_definition
from .release import saved_form_monitor


def _numeric_readings(snapshot) -> dict:
    """Recorded numeric readings by reading id."""
    return {
        stream.definition.id: stream
        for stream in snapshot.catalog.streams(selected_only=True)
        if stream.value_type == "number"
    }


def _setup_form(setup: MonitorSetup, readings: dict) -> FormMonitorConfig:
    """The form configuration that watches the setup's readings."""
    missing = [reading for reading in setup.reading_ids if reading not in readings]
    if missing:
        raise ValidationError(
            f"Record these readings as numbers first: {', '.join(missing)}"
        )
    chosen = [readings[reading] for reading in setup.reading_ids]
    # Readings of one device, or of one broker without a device, share it.
    if len({stream.charger_id for stream in chosen}) != 1:
        raise ValidationError(
            "Monitor the readings of one device, or broker readings without a "
            "device, together"
        )
    try:
        return setup.form([stream.accepted_topic for stream in chosen])
    except PydanticValidationError as exc:
        raise ValidationError(
            "; ".join(
                error["msg"].removeprefix("Value error, ") for error in exc.errors()
            )
        ) from exc


def _form_request(config: FormMonitorConfig, readings: dict) -> PipelineApplyRequest:
    """The pipeline apply request equivalent to a form configuration."""
    try:
        definition = legacy_definition(config)
        inputs = form_inputs(config)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    by_topic = {stream.accepted_topic: reading for reading, stream in readings.items()}
    missing = [topic for _, topic in inputs if topic not in by_topic]
    if missing:
        raise ValidationError(
            f"Select these topics as numeric readings first: {', '.join(missing)}"
        )
    bindings = {
        f"input_{index + 1}": by_topic[topic] for index, (_, topic) in enumerate(inputs)
    }
    # Slots show the catalogue label, not the recorded feature key.
    slots = [
        slot.model_copy(update={"label": readings[bindings[slot.id]].definition.label})
        for slot in definition.input_slots
    ]
    return PipelineApplyRequest(
        definition=definition.model_copy(update={"input_slots": slots}),
        bindings=bindings,
        display_name=(config.display_name or config.container_name)[:120],
        idempotency_key=f"form-{uuid4()}",
    )


async def start_form_monitor(session, setup: MonitorSetup) -> PipelineActivationView:
    """Convert a form setup into its equivalent graph and activate it."""
    readings = _numeric_readings(await read_collection_runtime(session))
    config = _setup_form(setup, readings)
    request = _form_request(config, readings)
    return await PipelineActivations(session).apply_form(
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
        readings = _numeric_readings(await read_collection_runtime(session))
        request = _form_request(config, readings)
        return await PipelineActivations(session).form_launch(request, config)
    except (ValidationError, PydanticValidationError) as exc:
        raise UnconvertibleFormMonitor(str(exc)) from exc
    except DomainError as exc:
        # For example unapplied collection; the release waits instead.
        raise ValueError(str(exc)) from exc
