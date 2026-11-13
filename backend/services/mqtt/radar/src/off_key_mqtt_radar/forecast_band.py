"""What a forecaster step expected of an observation, and the band around it.

A forecaster step scores one feature against the forecast made for it. A
result names that forecast's point, so a chart can draw what was expected
beside what arrived. Where a boundary applies to the step's own score, the
result also carries the calibrated interval: the values whose score stays at
or below that boundary. A value outside it is above the boundary.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from aberrant.forecast import ResidualDetector
from aberrant.forecast.scores import interval

from .pipelines.plan import ExecutionPlan


def forecast_bounds(forecast, lead, threshold, score):
    """A complete finite interval, or no interval for this score and lead."""
    if threshold is not None and math.isfinite(threshold):
        low, high = interval(forecast, lead, threshold, score)
        if math.isfinite(low) and math.isfinite(high) and low <= high:
            return low, high
    return None, None


def _slot(plan: ExecutionPlan, detector_id: str, target: str) -> str | None:
    """The reading the target is, when no step changed its values."""
    for feature in plan.compiled.features[plan.detector_inputs[detector_id]]:
        if feature.name == target:
            return feature.slots[0] if feature.raw and len(feature.slots) == 1 else None
    return None


def forecast_entry(
    plan: ExecutionPlan,
    detector_id: str,
    detector: object,
    features: Mapping[str, float] | None,
    threshold: float | None,
) -> dict[str, Any] | None:
    """One forecaster step's expectation for the observation it just scored.

    Read it after the step scored the observation and before it learns it: a
    pretrained step fetches a forecast its service missed while it scores.
    `threshold` is the boundary on this step's own score, or None when the run
    has none in those units.
    """
    if not isinstance(detector, ResidualDetector) or not features:
        return None
    forecast = detector.forecast_for(features)
    if forecast is None:
        return None
    lead = detector.lead
    lower, upper = forecast_bounds(forecast, lead, threshold, detector.score)
    return {
        "detector_id": detector_id,
        "target": detector.target,
        "slot": _slot(plan, detector_id, detector.target),
        "lead": lead,
        "expected": forecast.point(lead),
        "lower": lower,
        "upper": upper,
    }
