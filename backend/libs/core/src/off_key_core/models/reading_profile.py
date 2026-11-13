"""What a reading looks like, so a design can be fitted to it.

A design is chosen for its data: how often a value arrives, how far it moves,
whether it follows the time of day, how long it stays the same. A profile says
those things in numbers. It is made from two views of the stored history that
the charts already use: the lowest and highest value of each stretch of the
whole window, and the newest values as they arrived.
"""

import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta
from itertools import pairwise
from statistics import fmean, median

from ..schemas.devices import ReadingProfile, RecentValues

DAY = timedelta(days=1)
# A window is cut into at most this many stretches, none shorter than the first.
MIN_BUCKET = timedelta(minutes=15)
MAX_BUCKETS = 2000
# The newest values that say how a reading arrives.
RECENT_VALUES = 5000
# A gap this many times the usual one is a gap and not jitter.
_GAP_FACTOR = 5
# A reading with no more distinct values than this is a state, and they are listed.
_LEVELS = 10


def bucket_width(start: datetime, end: datetime) -> timedelta:
    """The stretch of time one bucket covers in a window."""
    return max(MIN_BUCKET, (end - start) / MAX_BUCKETS)


def _short(value: float) -> float:
    """Six significant digits: a profile is read, not computed with."""
    return float(f"{value:.6g}")


def _quantile(ordered: Sequence[float], share: float) -> float:
    """The value a share of the ordered values lies below, between neighbours."""
    position = share * (len(ordered) - 1)
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _explained(levels: Sequence[float], groups: Sequence[object]) -> float | None:
    """The share of a reading's variation that its groups explain, from 0 to 1.

    Adjusted for how many groups there are, so many small groups do not
    explain noise: random values answer with about 0.
    """
    count, kinds = len(levels), len(set(groups))
    if count <= kinds or kinds < 2:
        return None
    mean = fmean(levels)
    total = sum((level - mean) ** 2 for level in levels)
    if total <= 0:
        return None
    members: dict[object, list[float]] = defaultdict(list)
    for level, group in zip(levels, groups, strict=True):
        members[group].append(level)
    within = sum(
        sum((level - fmean(values)) ** 2 for level in values)
        for values in members.values()
    )
    adjusted = 1 - (within / (count - kinds)) / (total / (count - 1))
    return round(min(max(adjusted, 0.0), 1.0), 2)


def _recent(samples: Sequence[tuple[datetime, float | None]]) -> RecentValues | None:
    """How the newest values arrive and move; ``samples`` are oldest first."""
    kept = [(at, value) for at, value in samples if value is not None]
    if not kept:
        return None
    times = [at for at, _ in kept]
    values = [value for _, value in kept]
    ordered = sorted(values)
    gaps = [
        (later - earlier).total_seconds()
        for earlier, later in pairwise(times)
        if later > earlier
    ]
    usual = median(gaps) if gaps else None
    changes = [abs(later - earlier) for earlier, later in pairwise(values)]
    longest_flat, since = 0.0, times[0]
    for index in range(1, len(values)):
        if values[index] != values[index - 1]:
            since = times[index]
        longest_flat = max(longest_flat, (times[index] - since).total_seconds())
    distinct = sorted(set(values))
    mean = fmean(values)
    return RecentValues(
        count=len(values),
        missing=len(samples) - len(values),
        first=times[0],
        last=times[-1],
        interval_seconds=None if usual is None else _short(usual),
        interval_p90_seconds=None if not gaps else _short(_quantile(sorted(gaps), 0.9)),
        gaps=sum(gap > _GAP_FACTOR * usual for gap in gaps) if usual else 0,
        longest_gap_seconds=_short(max(gaps)) if gaps else None,
        mean=_short(mean),
        spread=_short(math.sqrt(fmean((value - mean) ** 2 for value in values))),
        median=_short(_quantile(ordered, 0.5)),
        p05=_short(_quantile(ordered, 0.05)),
        p95=_short(_quantile(ordered, 0.95)),
        typical_change=_short(median(changes)) if changes else None,
        flat_share=round(sum(change == 0 for change in changes) / len(changes), 3)
        if changes
        else None,
        longest_flat_seconds=_short(longest_flat),
        distinct=len(distinct),
        levels=[_short(value) for value in distinct]
        if len(distinct) <= _LEVELS
        else None,
    )


def profile_reading(
    reading_id: str,
    start: datetime,
    end: datetime,
    extremes: Sequence[tuple[datetime, float]],
    newest: Sequence[tuple[datetime, float | None]],
) -> ReadingProfile:
    """The profile of a reading over a window.

    ``extremes`` are the lowest and highest value of each bucket of the window
    (``bucket_width``), in time order. ``newest`` are its newest values, oldest
    first; those from before the window are left out.
    """
    width = bucket_width(start, end)
    buckets: dict[int, list[float]] = defaultdict(list)
    for at, value in extremes:
        if start <= at <= end:
            buckets[int((at - start) / width)].append(value)
    recent = _recent([(at, value) for at, value in newest if start <= at <= end])
    profile = ReadingProfile(
        reading_id=reading_id,
        start=start,
        end=end,
        bucket_seconds=_short(width.total_seconds()),
        recent=recent,
    )
    if not buckets:
        return profile
    filled = sorted(buckets)
    # The middle of what a bucket holds stands for its level.
    levels = [(min(buckets[index]) + max(buckets[index])) / 2 for index in filled]
    middles = [start + (index + 0.5) * width for index in filled]
    span = (filled[-1] - filled[0] + 1) * width
    longest_empty = max(
        (later - earlier - 1 for earlier, later in pairwise(filled)),
        default=0,
    )
    profile.first = min(at for at, _ in extremes if start <= at <= end)
    profile.last = max(at for at, _ in extremes if start <= at <= end)
    profile.coverage = round(len(filled) / (filled[-1] - filled[0] + 1), 3)
    profile.longest_outage_seconds = _short((longest_empty * width).total_seconds())
    profile.minimum = _short(min(min(values) for values in buckets.values()))
    profile.maximum = _short(max(max(values) for values in buckets.values()))
    if span >= 2 * DAY:
        profile.daily_rhythm = _explained(levels, [at.hour for at in middles])
        mean = fmean(levels)
        spread = math.sqrt(fmean((level - mean) ** 2 for level in levels))
        first_day = [
            level
            for level, at in zip(levels, middles, strict=True)
            if at < middles[0] + DAY
        ]
        last_day = [
            level
            for level, at in zip(levels, middles, strict=True)
            if at > middles[-1] - DAY
        ]
        if spread > 0:
            profile.level_change = round(
                (fmean(last_day) - fmean(first_day)) / spread, 2
            )
    if span >= 14 * DAY:
        profile.weekly_rhythm = _explained(
            levels, [(at.weekday(), at.hour) for at in middles]
        )
    return profile
