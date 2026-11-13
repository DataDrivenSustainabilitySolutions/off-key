"""Issued forecasts, separate from the forecast used to score an observation.

Read the forecast already issued by learn_one; never run inference a second time.
Leads count model updates. Wall-clock targets are explicitly estimates from recent
accepted observations, and stay absent until their cadence can be established.
"""

from collections import deque
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any

from aberrant.base.forecast import Forecast
from aberrant.forecast import ResidualDetector
from off_key_core.utils.timestamps import parse_utc_timestamp

from .forecast_band import forecast_bounds
from .forecast_records import MAX_ISSUED_POINTS


def issued_forecast(detector: object, threshold: float | None) -> dict | None:
    if not isinstance(detector, ResidualDetector) or detector.lead < 1:
        return None
    # Aberrant 1.5 has no public accessor for the newest issued forecast. Keep
    # this version-specific read here; forecast_for() returns an older forecast
    # when lead > 1. The deque is part of its checkpointed state.
    issued = detector._issued
    forecast = issued[-1] if issued else None
    if not isinstance(forecast, Forecast):
        return None
    leads = [lead for lead in forecast.leads if lead > 0]
    if len(leads) > MAX_ISSUED_POINTS:
        # Retain real points, including both ends and the calibrated lead.
        selected = {
            leads[round(i * (len(leads) - 1) / (MAX_ISSUED_POINTS - 2))]
            for i in range(MAX_ISSUED_POINTS - 1)
        }
        selected.add(detector.lead)
        leads = sorted(selected.intersection(leads))
    points = []
    for lead in leads:
        # A boundary calibrated for h updates does not calibrate other leads.
        lower, upper = forecast_bounds(
            forecast, lead, threshold if lead == detector.lead else None, detector.score
        )
        points.append(
            {
                "lead": lead,
                "target_step": forecast.origin + lead,
                "target_time": None,
                "expected": forecast.point(lead),
                "lower": lower,
                "upper": upper,
            }
        )
    return {
        "issued_at": datetime.now(UTC).isoformat(),
        "origin_step": forecast.origin,
        "origin_time": None,
        "time_basis": "unavailable",
        "step_seconds": None,
        "points": points,
    }


class ForecastTimeline:
    """Small, disposable timing estimates per detector, never model state.

    After a restart, missing, repeated or backwards time, gather three new
    consecutive intervals. Irregular observations retain forecasts in update
    coordinates without inventing a position on the time axis.
    """

    def __init__(self):
        self._previous: dict[str, tuple[int, datetime]] = {}
        self._intervals: dict[str, deque[float]] = {}

    def stamp(self, entries: list[dict], plan, timestamp: datetime, inputs: dict):
        bindings = {item.slot_id: item.input_key for item in plan.execution.bindings}
        for entry in entries:
            issued = entry.get("issued")
            if not issued:
                continue
            key = bindings.get(entry["slot"])
            try:
                origin_time = parse_utc_timestamp(inputs.get(key) if key else timestamp)
            except (ValueError, TypeError, OverflowError, OSError):
                self._previous.pop(entry["detector_id"], None)
                self._intervals.pop(entry["detector_id"], None)
                continue
            self._stamp(entry["detector_id"], issued, origin_time)

    def _stamp(self, identifier: str, issued: dict[str, Any], origin_time: datetime):
        origin = issued["origin_step"]
        issued["origin_time"] = origin_time.isoformat()
        previous = self._previous.get(identifier)
        # Attaching the same metadata twice must not advance timing state.
        if previous == (origin, origin_time):
            return
        intervals = self._intervals.setdefault(identifier, deque(maxlen=8))
        if previous:
            elapsed = (origin_time - previous[1]).total_seconds()
            if origin == previous[0] + 1 and 0 < elapsed <= 86_400:
                intervals.append(elapsed)
            else:
                intervals.clear()
        self._previous[identifier] = (origin, origin_time)
        if len(intervals) < 3:
            return
        step = median(intervals)
        if any(abs(value - step) > step * 0.2 for value in intervals):
            return
        issued["step_seconds"] = step
        issued["time_basis"] = "estimated_cadence"
        for point in issued["points"]:
            try:
                point["target_time"] = (
                    origin_time + timedelta(seconds=step * point["lead"])
                ).isoformat()
            except OverflowError:
                point["target_time"] = None
