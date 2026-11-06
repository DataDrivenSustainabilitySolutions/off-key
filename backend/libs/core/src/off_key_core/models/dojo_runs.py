"""Bind a detection design to the series of a Dojo dataset.

A replay runs the design exactly as a monitor would, so every series gets a
synthetic telemetry topic of one synthetic entity. TACTIC binds when a run is
created; the worker only executes the stored result.
"""

from dataclasses import dataclass

from ..schemas.pipelines import BoundInput, PipelineDefinition, PipelineExecutionConfig
from ..utils.mqtt_topics import derive_monitoring_sensor_keys
from .pipelines import execution_fingerprint

DOJO_ENTITY = "dojo"
DOJO_SENSOR_KEY_STRATEGY = "full_hierarchy"


def series_topic(position: int) -> str:
    """The topic one dataset series is replayed on."""
    return f"telemetry/{DOJO_ENTITY}/s{position}"


@dataclass(frozen=True)
class BoundSeries:
    id: str
    position: int
    name: str
    unit: str | None


def bind_dataset(
    definition: PipelineDefinition,
    series_by_slot: dict[str, BoundSeries],
    *,
    run_id: str,
) -> PipelineExecutionConfig:
    """The executable configuration of a compiled design over dataset series.

    A series without a unit takes the unit its slot declares; a series with a
    different unit is refused, as a live binding would be.
    """
    slots = definition.input_slots
    if set(series_by_slot) != {slot.id for slot in slots}:
        raise ValueError("Bind every input slot of the design exactly once")
    if len({item.id for item in series_by_slot.values()}) != len(series_by_slot):
        raise ValueError("Bind each series to at most one input slot")
    topics = [series_topic(series_by_slot[slot.id].position) for slot in slots]
    keys = derive_monitoring_sensor_keys(
        topics, sensor_key_strategy=DOJO_SENSOR_KEY_STRATEGY
    )
    bindings = []
    for slot, topic, key in zip(slots, topics, keys, strict=True):
        series = series_by_slot[slot.id]
        if slot.unit is not None and series.unit not in (None, slot.unit):
            raise ValueError(
                f"Series {series.name!r} is in {series.unit} but input "
                f"{slot.id!r} expects {slot.unit}"
            )
        bindings.append(
            BoundInput(
                slot_id=slot.id,
                reading_id=series.id,
                entity_id=DOJO_ENTITY,
                accepted_topic=topic,
                input_key=key,
                unit=slot.unit if slot.unit is not None else series.unit,
            )
        )
    return PipelineExecutionConfig(
        definition=definition,
        bindings=bindings,
        revision_id="dojo",
        run_id=run_id,
        fingerprint=execution_fingerprint(definition, bindings),
    )
