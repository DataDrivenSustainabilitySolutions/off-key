"""Bounded, backwards-compatible JSON for issued forecast evidence."""

import math
from typing import Any

from off_key_core.schemas.forecast import MAX_HORIZON
from off_key_core.utils.timestamps import parse_utc_timestamp

MAX_ISSUED_POINTS = 64


def _finite(value):
    return (
        float(value)
        if isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        else None
    )


def _time(value):
    try:
        return parse_utc_timestamp(value)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def normalize_issued_forecast(value: Any, calibrated_lead: int | None) -> dict | None:
    if not isinstance(value, dict):
        return None
    origin, issued_at = value.get("origin_step"), _time(value.get("issued_at"))
    if (
        not isinstance(origin, int)
        or isinstance(origin, bool)
        or origin < 0
        or issued_at is None
        or not isinstance(value.get("points"), list)
    ):
        return None
    origin_time = _time(value.get("origin_time"))
    step = _finite(value.get("step_seconds"))
    timed = (
        value.get("time_basis") == "estimated_cadence"
        and origin_time is not None
        and step is not None
        and 0 < step <= 86_400
    )
    points = []
    previous = 0
    for point in value["points"][:MAX_ISSUED_POINTS]:
        if not isinstance(point, dict):
            continue
        lead, expected = point.get("lead"), _finite(point.get("expected"))
        if (
            not isinstance(lead, int)
            or isinstance(lead, bool)
            or not previous < lead <= MAX_HORIZON
            or expected is None
        ):
            continue
        previous = lead
        lower, upper = _finite(point.get("lower")), _finite(point.get("upper"))
        banded = (
            lead == calibrated_lead
            and lower is not None
            and upper is not None
            and lower <= upper
        )
        target = _time(point.get("target_time")) if timed else None
        if (
            target is not None
            and abs((target - origin_time).total_seconds() - step * lead) > 0.001
        ):
            target = None
        points.append(
            {
                "lead": lead,
                "target_step": origin + lead,
                "target_time": target.isoformat() if target is not None else None,
                "expected": expected,
                "lower": lower if banded else None,
                "upper": upper if banded else None,
            }
        )
    if not points:
        return None
    return {
        "issued_at": issued_at.isoformat(),
        "origin_step": origin,
        "origin_time": origin_time.isoformat() if origin_time else None,
        "time_basis": "estimated_cadence" if timed else "unavailable",
        "step_seconds": step if timed else None,
        "points": points,
    }
