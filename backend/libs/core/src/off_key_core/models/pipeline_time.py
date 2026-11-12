"""Features of the time an observation was measured at.

A Prepare stage tells each step that reads time when its observation was
measured and how long after the step's previous one. A Time features step
turns that into features: dt, the seconds since the previous observation, and
where the observation falls in the day and the week of a time zone. A Smooth
by time constant reads the same seconds (pipeline_prepare.py).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from ..schemas.pipelines import TIME_SETTINGS, FeatureDescription, TimeParameters
from .pipeline_prepare import Bounds, PrepareFailure
from .pipeline_scope import ScopeError

# The smallest positive number: the minimum of a feature that is always above
# 0, so dividing by it skips nothing.
POSITIVE = math.ulp(0.0)
_CYCLE: Bounds = (-1.0, 1.0)
# The features each setting adds, in output order, with the values they take.
TIME_FEATURES: dict[str, tuple[tuple[str, Bounds], ...]] = {
    "elapsed": (("dt", (POSITIVE, None)),),
    "hour": (("hour", (0.0, 24.0)),),
    "weekday": (("weekday", (1.0, 7.0)),),
    "daily_cycle": (("hour_sin", _CYCLE), ("hour_cos", _CYCLE)),
    "weekly_cycle": (("weekday_sin", _CYCLE), ("weekday_cos", _CYCLE)),
}


@dataclass(frozen=True)
class Clock:
    """When the observation a step runs on was measured."""

    now: float
    """Seconds since the epoch."""
    elapsed: float | None
    """Seconds since the step's previous observation, above 0; None on its first."""


def _chosen(params: Mapping[str, Any]) -> list[str]:
    """The settings switched on, with the defaults of a draft that leaves them out."""
    fields = TimeParameters.model_fields
    return [
        name for name in TIME_SETTINGS if params.get(name, fields[name].default) is True
    ]


def time_names(params: Mapping[str, Any]) -> list[str]:
    """The features a Time features step adds, in order."""
    return [name for setting in _chosen(params) for name, _ in TIME_FEATURES[setting]]


def time_columns(
    params: Mapping[str, Any], columns: list[FeatureDescription]
) -> list[FeatureDescription]:
    """The features after a Time features step: those that arrive, then its own."""
    arriving = {item.name for item in columns}
    added = []
    for setting in _chosen(params):
        for name, (low, high) in TIME_FEATURES[setting]:
            if name in arriving:
                raise ScopeError(
                    f"{name} already arrives here. Rename that feature before "
                    "this step.",
                    setting,
                )
            added.append(
                FeatureDescription(
                    name=name, slots=[], minimum=low, maximum=high, raw=False
                )
            )
    return [*columns, *added]


class TimeFeatures:
    """Add the seconds since the previous observation, the hour and the weekday.

    The hour and the weekday follow the clock of one time zone, so a daily
    pattern stays in place across daylight saving time. The cycles place them
    on a circle, where the end of a day or a week lies next to its start.
    """

    def __init__(self, settings: TimeParameters):
        self.names = tuple(time_names(settings.model_dump()))
        self.elapsed = settings.elapsed
        self.calendar = self.names != ("dt",)
        self.zone: tzinfo = (
            UTC if settings.timezone == "UTC" else ZoneInfo(settings.timezone)
        )

    def apply(self, row: Mapping[str, float], clock: Clock) -> dict[str, float] | None:
        """The row with its time features; None while dt has nothing to measure from."""
        if self.elapsed and clock.elapsed is None:
            return None
        values = self._calendar(clock.now) if self.calendar else {}
        if clock.elapsed is not None:
            values["dt"] = clock.elapsed
        return {**row, **{name: values[name] for name in self.names}}

    def _calendar(self, now: float) -> dict[str, float]:
        try:
            moment = datetime.fromtimestamp(now, self.zone)
        except (OverflowError, OSError, ValueError) as error:
            raise PrepareFailure(
                "out_of_range", "The observation's time is outside the calendar"
            ) from error
        seconds = moment.second + moment.microsecond / 1_000_000
        hour = moment.hour + moment.minute / 60 + seconds / 3600
        day = 2 * math.pi * hour / 24
        week = 2 * math.pi * (moment.weekday() + hour / 24) / 7
        return {
            "hour": hour,
            "weekday": float(moment.isoweekday()),
            "hour_sin": math.sin(day),
            "hour_cos": math.cos(day),
            "weekday_sin": math.sin(week),
            "weekday_cos": math.cos(week),
        }


__all__ = [
    "POSITIVE",
    "TIME_FEATURES",
    "Clock",
    "TimeFeatures",
    "time_columns",
    "time_names",
]
