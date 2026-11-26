"""Calibration steps: what each takes, from the generated method catalog.

A calibration step turns the detectors' scores into what the alarm policy
decides on. The fixed split freezes after the calibration window. Every other
method keeps adapting a boundary that a target share of scores stays below;
those methods run in RADAR from ``aberrant.calibration`` and are described here
by ``calibration_catalog.json``, so the control plane imports no numerics.
"""

import json
import math
from importlib.resources import files
from typing import Annotated, Any

from pydantic import Field, create_model

from ..schemas.pipeline_versions import CALIBRATION_PREFIX, FIXED_SPLIT
from ..schemas.pipelines import FusionMode, PipelineModel

CALIBRATION_CATALOG: dict[str, Any] = json.loads(
    files(__package__).joinpath("calibration_catalog.json").read_text()
)
# The adapting methods by id, in the order they are offered.
CALIBRATORS: dict[str, dict[str, Any]] = {
    identifier: CALIBRATION_CATALOG["calibrators"][identifier]
    for identifier in CALIBRATION_CATALOG["order"]
}
# Methods whose boundary is a quantile of the calibration window itself: with
# too few scores for the alarm rate, it is the window's largest score.
WINDOW_QUANTILE_METHODS = frozenset({"split", "aci", "dtaci", "agaci"})
EXCEEDANCE_RULE = "policy.exceedance"

Fusion = Annotated[
    FusionMode,
    Field(
        title="Combine detectors",
        description=(
            "How several detectors raise one alarm. Each score becomes a surprise "
            "against that detector's calibration scores; max follows the strongest "
            "surprise, mean their average. With one detector this has no effect."
        ),
    ),
]
AlarmRate = Annotated[
    float,
    Field(
        gt=0,
        lt=1,
        title="Target alarm rate",
        description=(
            "The share of scores above the boundary in the long run. It counts "
            "every score above the boundary, anomalies included, so it is not "
            "the false alarm rate."
        ),
    ),
]


class CalibrationParameters(PipelineModel):
    """How a calibration step combines the detectors that feed it."""

    fusion: Fusion = "max"


class ExceedanceRuleParameters(PipelineModel):
    """When scores above the calibrated boundary raise an alarm."""

    consecutive: int = Field(
        default=1,
        ge=1,
        le=1000,
        title="Exceedances in a row",
        description=(
            "Alarm once this many scores in a row are above the boundary. More "
            "than one ignores short spikes. The alarm rate then falls below the "
            "target, but not to its power: exceedances tend to come together."
        ),
    )


class FixedThresholdParameters(PipelineModel):
    """The score the design alarms at, set by hand rather than calibrated."""

    value: float = Field(
        default=1.0,
        allow_inf_nan=False,
        title="Alarm at or above",
        description=(
            "A score at or above this value raises an alarm. For a rule that "
            "scores a 0/1 flag, 1 alarms on every 1. Nothing is calibrated, so "
            "scoring starts as soon as the detector is ready."
        ),
    )


def calibrator_id(component: str) -> str | None:
    """The adapting method a calibration component runs; none for the fixed split."""
    method = component.removeprefix(CALIBRATION_PREFIX)
    return method if component != FIXED_SPLIT and method in CALIBRATORS else None


_BOUNDS = {
    "minimum": "ge",
    "exclusiveMinimum": "gt",
    "maximum": "le",
    "exclusiveMaximum": "lt",
}


def _parameter(schema: dict[str, Any]) -> tuple[type, Any]:
    kind = int if schema["type"] == "integer" else float
    return kind, Field(
        default=kind(schema["default"]),
        title=schema["title"],
        description=schema.get("description") or None,
        **{_BOUNDS[key]: value for key, value in schema.items() if key in _BOUNDS},
    )


def _calibrator_model(method: str) -> type[PipelineModel]:
    spec = CALIBRATORS[method]
    fields: dict[str, Any] = {"alpha": (AlarmRate, 0.01)}
    fields.update(
        {
            name: _parameter(schema)
            for name, schema in spec["parameters"]["properties"].items()
        }
    )
    fields["fusion"] = (Fusion, "max")
    name = "".join(part.title() for part in method.split("_"))
    return create_model(
        f"{name}CalibrationParameters", __base__=PipelineModel, **fields
    )


CALIBRATION_MODELS: dict[str, type[PipelineModel]] = {
    FIXED_SPLIT: CalibrationParameters,
    **{
        f"{CALIBRATION_PREFIX}{method}": _calibrator_model(method)
        for method in CALIBRATORS
    },
}


def minimum_window(method: str, alpha: float, detectors: int, fusion: str) -> int:
    """The calibration observations a boundary at this alarm rate needs.

    A window of n scores puts its (1 - alpha) conformal quantile below its
    largest score only when (n + 1) * alpha >= 2. With fewer, the boundary is
    the largest score of the window: one spike lifts it for as long as the
    window holds the spike, and the monitor misses anything smaller. Several
    detectors meet as ranks in the window, whose largest value each of them
    reaches about once in n scores.
    """
    if detectors < 2 and method not in WINDOW_QUANTILE_METHODS:
        return 1
    reach = detectors if detectors > 1 and fusion == "max" else 1
    return max(math.ceil(2 * reach / alpha - 1e-9) - 1, 1)
