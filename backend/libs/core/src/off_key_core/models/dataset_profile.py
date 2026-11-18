"""A Dojo dataset as a whole: each series, how they move together, the labels.

An agent chooses a design from what it knows of the data. A dataset profile
says in numbers what a person sees on its charts: the course of each series,
how it arrives and moves, whether its level stays, its cycles, which series
move together and whether the labels show in the values.
"""

import math
from bisect import bisect_right
from collections.abc import Sequence
from datetime import datetime, timedelta
from itertools import pairwise
from operator import mul
from statistics import fmean, median

from ..schemas.dojo import (
    DatasetProfile,
    LabelCoverage,
    SeriesBrief,
    SeriesPair,
    SeriesProfile,
    SeriesShape,
)
from .autocorrelation import MAX_VALUES, MIN_VALUES, Point, autocorrelation
from .reading_profile import describe_values

# Stretches a series' course is drawn in.
SHAPE_BUCKETS = 48
# Values on the shared grid that pairs of series are measured on.
PAIR_VALUES = 512
# Steps either way a pair's changes are compared at.
PAIR_LEADS = 5
PAIR_LEVEL = 0.5
MAX_PAIRS = 20
# The share of a series at each end its level change compares.
_ENDS = 0.1

Interval = tuple[datetime, datetime]


def _short(value: float) -> float:
    return float(f"{value:.4g}")


def _spread(values: Sequence[float]) -> float:
    mean = fmean(values)
    return math.sqrt(fmean((value - mean) ** 2 for value in values))


def shape(points: Sequence[Point], buckets: int = SHAPE_BUCKETS) -> SeriesShape | None:
    """The series in equal stretches of its span, oldest first."""
    if len(points) < 2 or points[-1][0] <= points[0][0]:
        return None
    start = points[0][0]
    width = (points[-1][0] - start) / buckets
    members: list[list[float]] = [[] for _ in range(buckets)]
    for at, value in points:
        members[min(int((at - start) / width), buckets - 1)].append(value)
    return SeriesShape(
        start=start,
        bucket_seconds=_short(width.total_seconds()),
        mean=[_short(fmean(item)) if item else None for item in members],
        low=[_short(min(item)) if item else None for item in members],
        high=[_short(max(item)) if item else None for item in members],
    )


def level_change(values: Sequence[float]) -> float | None:
    """The last tenth's mean minus the first tenth's, in spreads."""
    size = int(len(values) * _ENDS)
    if size < 2:
        return None
    spread = _spread(values)
    if spread <= 0:
        return None
    return round((fmean(values[-size:]) - fmean(values[:size])) / spread, 2)


def _inside(at: datetime, labels: Sequence[Interval], starts: list[datetime]) -> bool:
    index = bisect_right(starts, at) - 1
    return index >= 0 and at <= labels[index][1]


def labelled_shift(points: Sequence[Point], labels: Sequence[Interval]) -> float | None:
    """Mean inside the labels minus the mean outside, in spreads."""
    if not labels:
        return None
    starts = [start for start, _ in labels]
    inside, outside = [], []
    for at, value in points:
        (inside if _inside(at, labels, starts) else outside).append(value)
    if not inside or not outside:
        return None
    spread = _spread([value for _, value in points])
    if spread <= 0:
        return None
    return round((fmean(inside) - fmean(outside)) / spread, 2)


def _brief[Brief: SeriesBrief](
    series_id: str,
    name: str,
    points: Sequence[Point],
    total: int | None,
    labels: Sequence[Interval],
    model: type[Brief],
) -> Brief:
    gaps = [
        (later - earlier).total_seconds()
        for (earlier, _), (later, _) in pairwise(points)
        if later > earlier
    ]
    values = [value for _, value in points]
    brief = model(
        series_id=series_id,
        name=name,
        count=len(points) if total is None else total,
        first=points[0][0] if points else None,
        last=points[-1][0] if points else None,
        interval_seconds=_short(median(gaps)) if gaps else None,
        values=describe_values(points),
        level_change=level_change(values),
        labelled_shift=labelled_shift(points, labels),
        shape=shape(points),
    )
    # The first values show short lags where a design learns; the whole
    # series on a coarser grid shows long cycles.
    scales = [autocorrelation(points[:MAX_VALUES])]
    if len(points) > MAX_VALUES:
        scales.append(autocorrelation(points))
    found = [item for item in scales if item is not None]
    if found:
        brief.persistent = found[0].persistent
        brief.lags = found[0].suggested_lags[:3]
        seen: set[float] = set()
        for item in reversed(found):
            for season in item.seasons:
                if season.seconds not in seen:
                    seen.add(season.seconds)
                    brief.cycles.append(season)
        brief.cycles.sort(key=lambda season: -season.strength)
    else:
        brief.notes.append(
            f"Too few values that vary: autocorrelation needs {MIN_VALUES}."
        )
    if total is not None and total > len(points):
        brief.notes.append(
            f"The profile reads the first {len(points)} of {total} values."
        )
    if isinstance(brief, SeriesProfile):
        brief.autocorrelation = found
    return brief


def profile_series(
    series_id: str,
    name: str,
    points: Sequence[Point],
    *,
    total: int | None = None,
    labels: Sequence[Interval] = (),
) -> SeriesProfile:
    """A Dojo series' profile from its points in time order."""
    return _brief(series_id, name, points, total, labels, SeriesProfile)


def _changes(values: Sequence[float]) -> list[float] | None:
    """Changes from one step to the next, centred and scaled to unit length."""
    changes = [later - earlier for earlier, later in pairwise(values)]
    return _unit(changes)


def _unit(values: Sequence[float]) -> list[float] | None:
    if len(values) < 2:
        return None
    mean = fmean(values)
    centred = [value - mean for value in values]
    norm = math.sqrt(sum(value * value for value in centred))
    return [value / norm for value in centred] if norm > 0 else None


def _correlation(first: Sequence[float], second: Sequence[float], lead: int) -> float:
    """Correlation of the first series ``lead`` steps before the second."""
    if lead >= 0:
        return sum(map(mul, first[: len(first) - lead], second[lead:]))
    return sum(map(mul, first[-lead:], second[: len(second) + lead]))


def pairs(
    series: Sequence[tuple[str, Sequence[Point]]],
) -> tuple[float | None, list[SeriesPair]]:
    """Pairs of series that move together, on a grid over the span they share."""
    timed = [(name, points) for name, points in series if len(points) >= MIN_VALUES]
    if len(timed) < 2:
        return None, []
    start = max(points[0][0] for _, points in timed)
    end = min(points[-1][0] for _, points in timed)
    if end <= start:
        return None, []
    usual = max(
        median(
            (later - earlier).total_seconds()
            for (earlier, _), (later, _) in pairwise(points)
            if later > earlier
        )
        for _, points in timed
    )
    step = max(usual, (end - start).total_seconds() / (PAIR_VALUES - 1))
    count = int((end - start).total_seconds() / step) + 1
    if count < MIN_VALUES:
        return None, []
    grids: list[tuple[str, list[float], list[float]]] = []
    for name, points in timed:
        times = [at for at, _ in points]
        grid = [
            points[bisect_right(times, start + timedelta(seconds=index * step)) - 1][1]
            for index in range(count)
        ]
        levels, changes = _unit(grid), _changes(grid)
        if levels is not None and changes is not None:
            grids.append((name, levels, changes))
    found: list[SeriesPair] = []
    for index, (first, levels_a, changes_a) in enumerate(grids):
        for second, levels_b, changes_b in grids[index + 1 :]:
            level = _correlation(levels_a, levels_b, 0)
            leads = {
                lead: _correlation(changes_a, changes_b, lead)
                for lead in range(-PAIR_LEADS, PAIR_LEADS + 1)
            }
            best = max(leads, key=lambda lead: (abs(leads[lead]), -abs(lead)))
            if max(abs(level), abs(leads[best])) < PAIR_LEVEL:
                continue
            found.append(
                SeriesPair(
                    first=first,
                    second=second,
                    level=round(level, 3),
                    change=round(leads[0], 3),
                    lead_seconds=_short(best * step),
                    lead_change=round(leads[best], 3),
                )
            )
    found.sort(key=lambda pair: -max(abs(pair.lead_change), abs(pair.level)))
    return _short(step), found[:MAX_PAIRS]


def _coverage(
    labels: Sequence[Interval], first: datetime | None, last: datetime | None
) -> LabelCoverage | None:
    if not labels:
        return None
    lengths = [(end - start).total_seconds() for start, end in labels]
    span = (last - first).total_seconds() if first and last else 0
    return LabelCoverage(
        count=len(labels),
        labelled_share=round(min(sum(lengths) / span, 1.0), 4) if span > 0 else 0,
        median_seconds=_short(median(lengths)),
    )


def profile_dataset(
    dataset_id: str,
    name: str,
    series: Sequence[tuple[str, str, Sequence[Point], int]],
    labels: Sequence[Interval] = (),
) -> DatasetProfile:
    """``series`` are (id, name, points in time order, how many values in all)."""
    briefs = [
        _brief(series_id, label, points, total, labels, SeriesBrief)
        for series_id, label, points, total in series
    ]
    firsts = [brief.first for brief in briefs if brief.first]
    lasts = [brief.last for brief in briefs if brief.last]
    first, last = min(firsts, default=None), max(lasts, default=None)
    step, found = pairs([(label, points) for _, label, points, _ in series])
    profile = DatasetProfile(
        dataset_id=dataset_id,
        name=name,
        first=first,
        last=last,
        series=briefs,
        step_seconds=step,
        pairs=found,
        labels=_coverage(labels, first, last),
    )
    if len(briefs) > 1 and step is None:
        profile.notes.append(
            "The series share too little time to say how they move together."
        )
    return profile
