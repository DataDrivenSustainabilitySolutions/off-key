"""How a series relates to its own past: context for choosing time steps.

A detector that treats observations as unrelated needs the time in a series
taken care of first, by lags, a decomposition or a forecast. Which lags and
which cycle is what the autocorrelation says. The functions here take a
series' points, so live readings and Dojo series share them.
"""

import math
from bisect import bisect_right
from collections.abc import Sequence
from datetime import datetime
from itertools import pairwise
from statistics import fmean, median

from ..schemas.devices import Autocorrelation, Season, SuggestedLag

# Fewer values than this say too little about a series' past.
MIN_VALUES = 32
# Values on one grid: more are put on a coarser one.
MAX_VALUES = 4096
MAX_LAGS = 200
MAX_PARTIAL_LAGS = 48
MAX_SUGGESTED = 8
MAX_SEASONS = 3
# Arrival spacing this uneven, or a gap this many usual intervals, makes a grid.
_UNEVEN = 1.5
_GAP = 5
# Still this correlated this many lags back, the series wanders or trends.
_PERSISTENT_LAG = 20
_PERSISTENT_LEVEL = 0.7
# A cycle must stand this far above the lowest correlation before it.
_SEASON_RISE = 0.1
_SEASON_FLOOR = 0.2

# Steps a coarser grid rounds up to, so a cycle comes out as a round time.
_STEPS = (
    1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800,
    3600, 7200, 10800, 21600, 43200, 86400,
)  # fmt: skip

Point = tuple[datetime, float]


def _round_step(seconds: float) -> float:
    """The shortest round step at least this long."""
    return next((step for step in _STEPS if step >= seconds), seconds)


def _short(value: float) -> float:
    return float(f"{value:.4g}")


def on_grid(points: Sequence[Point]) -> tuple[float, list[float], bool] | None:
    """A series on an even grid of time: the step, the values, and whether
    they arrived evenly. Points are in time order; repeated times keep the last.
    """
    if len(points) < MIN_VALUES:
        return None
    seconds = [at.timestamp() for at, _ in points]
    values = [value for _, value in points]
    gaps = [later - earlier for earlier, later in pairwise(seconds) if later > earlier]
    if not gaps:
        return None
    step = median(gaps)
    ordered = sorted(gaps)
    regular = (
        ordered[int(0.9 * (len(ordered) - 1))] <= _UNEVEN * step
        and ordered[int(0.1 * (len(ordered) - 1))] >= step / _UNEVEN
        and ordered[-1] <= _GAP * step
        and len(gaps) == len(points) - 1
    )
    span = seconds[-1] - seconds[0]
    if regular and len(values) <= MAX_VALUES:
        return step, values, True
    # The usual spacing, outages aside, so a grid does not repeat values.
    upper = ordered[int(0.75 * (len(ordered) - 1))]
    usual = fmean(gap for gap in gaps if gap <= _GAP * upper)
    step = _round_step(max(usual, span / (MAX_VALUES - 1)))
    count = int(span / step) + 1
    if count < MIN_VALUES:
        return None
    # The last value at or before each step.
    grid = [
        values[bisect_right(seconds, seconds[0] + index * step) - 1]
        for index in range(count)
    ]
    return step, grid, False


def _acf(values: Sequence[float], lags: int) -> list[float] | None:
    mean = fmean(values)
    centred = [value - mean for value in values]
    total = sum(item * item for item in centred)
    if total <= 0:
        return None
    return [
        sum(a * b for a, b in zip(centred, centred[lag:], strict=False)) / total
        for lag in range(1, lags + 1)
    ]


def _pacf(acf: Sequence[float], lags: int) -> list[float]:
    """Durbin-Levinson: each lag's coefficient once the shorter lags are known."""
    result: list[float] = []
    previous: list[float] = []
    for k in range(1, lags + 1):
        if k == 1:
            current = [acf[0]]
        else:
            numerator = acf[k - 1] - sum(
                previous[j] * acf[k - 2 - j] for j in range(k - 1)
            )
            denominator = 1 - sum(previous[j] * acf[j] for j in range(k - 1))
            if abs(denominator) < 1e-12:
                break
            last = numerator / denominator
            current = [
                previous[j] - last * previous[k - 2 - j] for j in range(k - 1)
            ] + [last]
        result.append(min(max(current[-1], -1.0), 1.0))
        previous = current
    return result


def _repeats(lag: int, cycle: int) -> bool:
    """Whether a lag lies within 10% of the cycle of a multiple of it."""
    multiple = max(round(lag / cycle), 1)
    return abs(lag - multiple * cycle) <= 0.1 * cycle


def _seasons(acf: Sequence[float], bound: float, step: float) -> list[Season]:
    found: list[tuple[float, int]] = []
    lowest = acf[0]
    for index in range(1, len(acf) - 1):
        lowest = min(lowest, acf[index - 1])
        value = acf[index]
        if (
            value > acf[index - 1]
            and value >= acf[index + 1]
            and value > max(bound, _SEASON_FLOOR)
            and value - lowest >= _SEASON_RISE
        ):
            found.append((value, index + 1))
    chosen: list[tuple[float, int]] = []
    for value, lag in sorted(found, reverse=True):
        # A peak near a multiple of a stronger cycle is that cycle again; a
        # weekly cycle stands above the daily one at a week, so it stays.
        if all(not _repeats(lag, other) for _, other in chosen):
            chosen.append((value, lag))
        if len(chosen) == MAX_SEASONS:
            break
    return [
        Season(observations=lag, seconds=_short(lag * step), strength=round(value, 3))
        for value, lag in chosen
    ]


def autocorrelation(points: Sequence[Point]) -> Autocorrelation | None:
    """How a series relates to its own past; None for too few or flat values."""
    grid = on_grid(points)
    if grid is None:
        return None
    step, values, regular = grid
    lags = min(MAX_LAGS, len(values) // 3)
    acf = _acf(values, lags)
    if acf is None or not acf:
        return None
    pacf = _pacf(acf, min(MAX_PARTIAL_LAGS, lags))
    bound = 1.96 / math.sqrt(len(values))
    strongest = sorted(
        (index + 1 for index, value in enumerate(pacf) if abs(value) > bound),
        key=lambda lag: -abs(pacf[lag - 1]),
    )[:MAX_SUGGESTED]
    persistent = acf[min(_PERSISTENT_LAG, len(acf)) - 1] > _PERSISTENT_LEVEL
    return Autocorrelation(
        step_seconds=_short(step),
        count=len(values),
        regular=regular,
        acf=[round(value, 3) for value in acf],
        pacf=[round(value, 3) for value in pacf],
        bound=round(bound, 3),
        persistent=persistent,
        suggested_lags=[
            SuggestedLag(
                observations=lag,
                seconds=_short(lag * step),
                partial=round(pacf[lag - 1], 3),
            )
            for lag in strongest
        ],
        seasons=_seasons(acf, bound, step),
    )
