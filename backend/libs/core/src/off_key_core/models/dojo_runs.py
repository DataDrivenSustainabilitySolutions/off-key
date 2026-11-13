"""Bind a detection design to the series of a Dojo dataset.

A replay runs the design exactly as a monitor would, so every series gets a
synthetic telemetry topic of one synthetic entity. TACTIC binds when a run is
created; the worker only executes the stored result.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..schemas.pipeline_versions import Strategy
from ..schemas.pipelines import (
    BoundInput,
    PipelineDefinition,
    PipelineExecutionConfig,
    PipelineValidation,
)
from ..utils.mqtt_topics import derive_monitoring_sensor_keys
from .pipeline_calibration import CALIBRATORS, EXCEEDANCE_RULE, calibrator_id
from .pipelines import execution_fingerprint

DOJO_ENTITY = "dojo"
DOJO_SENSOR_KEY_STRATEGY = "full_hierarchy"
# The fixed split among the adapting methods of ``aberrant.calibration``.
FIXED_METHOD = "fixed_split"
MARTINGALE_RULE = "policy.martingale"
# Where a finished run keeps what a few observations looked like at every
# step, beside its settings.
STEP_SAMPLES_KEY = "step_samples"


def result_kind(definition: Mapping[str, Any]) -> Strategy:
    """What a run's results are, from its stored design.

    The conformal alarm policy gives p-values (``static_baseline``); every
    other policy gives scores against a threshold (``adaptive_stream``).
    """
    martingale = any(
        node.get("component") == MARTINGALE_RULE for node in definition.get("nodes", [])
    )
    return "static_baseline" if martingale else "adaptive_stream"


def calibration_comparison(compiled: PipelineValidation) -> dict[str, Any] | None:
    """The calibration methods a run tries beside its own, and their settings.

    Every method sees the detector scores of the run, at one alarm rate and
    one number of exceedances in a row, so only the method differs. A fixed
    split names no alarm rate: its quantile leaves that share of scores above
    the threshold, and the largest calibration score leaves one in n + 1.
    A design that alarms on a conformal martingale has no boundary on its
    scores, so there is nothing to compare; it gets none.
    """
    nodes = {node.id: node for node in compiled.definition.nodes}
    policy = nodes[compiled.policy_id]
    if compiled.calibration_id is None or policy.component == MARTINGALE_RULE:
        return None
    calibration = nodes[compiled.calibration_id]
    adapting = calibrator_id(calibration.component)
    if adapting is None:
        window = compiled.definition.settings.calibration_window_size
        quantile = float(policy.params.get("quantile", 1.0))
        alpha = max(1.0 - quantile, 1.0 / (window + 1))
        consecutive = 1
    else:
        alpha = float(calibration.params["alpha"])
        consecutive = (
            int(policy.params.get("consecutive", 1))
            if policy.component == EXCEEDANCE_RULE
            else 1
        )
    own = adapting or FIXED_METHOD
    return {
        "own": own,
        "methods": [method for method in (FIXED_METHOD, *CALIBRATORS) if method != own],
        "alpha": alpha,
        "consecutive": consecutive,
    }


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
