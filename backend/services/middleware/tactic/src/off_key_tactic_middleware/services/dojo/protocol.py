"""The fault-injection protocol: which faults a protocol suite plants, where,
and how a study on it is scored.

A protocol suite holds one clean copy of a dataset and many copies with one
fault each, drawn from a fixed grid of fault families. Sizes are multiples of
the series' short-term noise, lengths count observations against the design's
calibration window W, and every fault starts after the design's warm-up and
keeps W clear of labels and gaps. The sizes of one family share their places
(common random numbers), so a difference between sizes is the size's own.

A study on the suite is held to a false-alarm budget on the clean copy first.
A fault counts as caught only when the faulted copy alarms inside it and the
clean copy does not over the same span, and catches are set against what the
design's alarm share would hit by chance. Each family gets a detection
profile: catch rate per size, with the size at which half and nine in ten of
its faults are caught.

Precedent: Sharma et al. 2010 (field sensor faults), Lai et al. 2021
(outlier taxonomy), GutenTAG (parameterised injection), Goswami et al. 2023
(injection into real series), Wu & Keogh 2021 (trivial baselines, density),
Kim et al. 2022 (chance credit), Lavin & Ahmad 2015 (false-alarm profiles).
"""

import bisect
import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from statistics import median
from typing import Literal

from off_key_core.schemas.dojo import (
    Fault,
    FaultKind,
    FaultProtocol,
    FaultRecovery,
    LabelOutcome,
    ProtocolFamily,
    ProtocolLevel,
    ProtocolReport,
    RunMetrics,
)

VERSION = 1
# The false-alarm budget a design meets on the clean copy before its catches
# count: alarm onsets per day and the share of results in alarm.
BUDGET_PER_DAY = 1.0
BUDGET_SHARE = 0.01
# Defaults when the caller does not say what the design needs.
WARMUP_SHARE = 0.3
WINDOW_SHARE = 0.05
MIN_WINDOW = 8
# A gap in the recorded values: this many typical intervals without a value.
GAP_FACTOR = 5
# Simple rules a design should beat (Wu & Keogh's trivial detectors).
RULE_SIGMAS = 4.0
RULE_REPEATS = 10
# Values read after a fault's start to judge it by the simple rules.
MAX_RULE_VALUES = 20_000
STRATA = 10
Length = Literal["short", "medium", "long", "very_long"]
Measure = Literal["sigmas", "factor", "values", "none"]


@dataclass(frozen=True)
class Family:
    key: str
    title: str
    kind: FaultKind
    measure: Measure
    levels: tuple[float, ...]
    replicates: int
    lengths: tuple[Length, ...] = ("medium",)
    onset: Literal["sudden", "slow"] = "sudden"
    recovery: FaultRecovery = "sudden"
    stuck: float | None = None
    common: bool = False
    # A sanity fault every design should catch; a miss is a bug, not a limit.
    sanity: bool = False


SIZES = (1.0, 2.0, 4.0, 8.0)
FACTORS = (2.0, 4.0, 8.0)
LENGTHS: tuple[Length, ...] = ("short", "medium", "long")

PRESETS: dict[FaultProtocol, tuple[Family, ...]] = {
    "screening-v1": (
        Family("step", "Sudden step", "step", "sigmas", SIZES, 2),
        Family(
            "slow-drift",
            "Slow drift, no recovery",
            "drift",
            "sigmas",
            SIZES,
            2,
            onset="slow",
            recovery="none",
        ),
        Family("gain", "Gain error", "gain", "sigmas", SIZES, 2),
        Family("noise", "Rising noise", "noise", "factor", FACTORS, 2),
        Family("spike", "Spike", "spike", "sigmas", SIZES, 1),
        Family("freeze", "Frozen value", "freeze", "values", (), 2, LENGTHS),
        Family("gap", "Gap", "gap", "values", (), 2, LENGTHS),
        Family(
            "out-of-range",
            "Impossible value",
            "out_of_range",
            "none",
            (),
            2,
            sanity=True,
        ),
    ),
    "full-v1": (
        Family("step", "Sudden step", "step", "sigmas", SIZES, 2),
        Family(
            "step-gradual",
            "Step, gradual recovery",
            "step",
            "sigmas",
            SIZES,
            2,
            recovery="gradual",
        ),
        Family(
            "step-lasting",
            "Step, no recovery",
            "step",
            "sigmas",
            SIZES,
            2,
            recovery="none",
        ),
        Family(
            "long-step",
            "Long step",
            "step",
            "sigmas",
            (2.0, 4.0, 8.0),
            1,
            ("long",),
        ),
        Family(
            "slow-drift",
            "Slow drift, gradual recovery",
            "drift",
            "sigmas",
            SIZES,
            2,
            onset="slow",
            recovery="gradual",
        ),
        Family(
            "slow-drift-lasting",
            "Slow drift, no recovery",
            "drift",
            "sigmas",
            SIZES,
            2,
            onset="slow",
            recovery="none",
        ),
        Family(
            "very-slow-drift",
            "Very slow drift",
            "drift",
            "sigmas",
            (2.0, 4.0, 8.0),
            2,
            ("very_long",),
            onset="slow",
            recovery="none",
        ),
        Family("gain", "Gain error", "gain", "sigmas", SIZES, 2),
        Family("noise", "Rising noise", "noise", "factor", FACTORS, 2),
        Family("spike", "Spike", "spike", "sigmas", SIZES, 2),
        Family("freeze", "Frozen value", "freeze", "values", (), 2, LENGTHS),
        Family("stuck-zero", "Stuck at 0", "freeze", "values", (), 2, stuck=0.0),
        Family("gap", "Gap", "gap", "values", (), 2, LENGTHS),
        Family(
            "common-mode",
            "Common-mode step",
            "step",
            "sigmas",
            (2.0, 4.0),
            2,
            common=True,
        ),
        Family(
            "out-of-range",
            "Impossible value",
            "out_of_range",
            "none",
            (),
            2,
            sanity=True,
        ),
    ),
}


@dataclass(frozen=True)
class Cell:
    family: Family
    level: float | None
    length: Length
    replicate: int

    @property
    def id(self) -> str:
        level = "" if self.level is None else f"-{self.level:g}"
        return f"{self.family.key}{level}-{self.length}-{self.replicate}"

    @property
    def group(self) -> tuple[str, str, int]:
        """The cells that share a place: one family, length and replicate."""
        return self.family.key, self.length, self.replicate


def cells(protocol: FaultProtocol, series_count: int) -> list[Cell]:
    found = []
    for family in PRESETS[protocol]:
        if family.common and series_count < 2:
            continue
        for length in family.lengths:
            for replicate in range(1, family.replicates + 1):
                found.extend(
                    Cell(family, level, length, replicate)
                    for level in family.levels or (None,)
                )
    return found


def hold_values(length: Length, window: int) -> int:
    return {
        "short": 8,
        "medium": max(10, window // 4),
        "long": 2 * window,
        "very_long": 5 * window,
    }[length]


def span_values(cell: Cell, window: int) -> int:
    """Observations from the fault's start to the end of its scoring horizon."""
    hold = 1 if cell.family.kind == "spike" else hold_values(cell.length, window)
    recovery = hold if cell.family.recovery == "gradual" else 0
    return hold + recovery + 2 * window


@dataclass(frozen=True)
class Timeline:
    """The recorded timestamps of one series, as epoch seconds."""

    series_id: str
    times: Sequence[float]
    blocked: Sequence[tuple[int, int]]

    @classmethod
    def of(
        cls,
        series_id: str,
        times: Sequence[float],
        labels: Sequence[tuple[float, float]],
        window: int,
    ) -> "Timeline":
        """Index ranges a fault may not touch: labels and real gaps, with W
        observations of margin on either side."""
        blocked = []
        for start, end in labels:
            low = bisect.bisect_left(times, start)
            high = bisect.bisect_right(times, end)
            blocked.append((low - window, high + window))
        if len(times) > 2:
            steps = [b - a for a, b in pairwise(times)]
            typical = median(steps)
            for index, step in enumerate(steps):
                if typical > 0 and step > GAP_FACTOR * typical:
                    blocked.append((index - window, index + 1 + window))
        return cls(series_id, times, blocked)

    def free(self, start: int, span: int) -> bool:
        end = start + span
        return all(end < low or start > high for low, high in self.blocked)


@dataclass(frozen=True)
class Placement:
    cell: Cell
    series_id: str
    start: int
    fault: Fault
    cut: datetime


def _moment(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, UTC)


def place(
    protocol: FaultProtocol,
    timelines: Mapping[str, Timeline],
    warmup: int,
    window: int,
    seed: int,
) -> tuple[list[Placement], list[str]]:
    """Every cell of the grid at a drawn place, and the cells with no room.

    A cell that does not fit is reported as not testable on this history;
    nothing is shrunk to make it fit, since that would change what it tests.
    """
    draw = random.Random(seed)
    order = list(timelines)
    grid = cells(protocol, len(order))
    places: dict[tuple[str, str, int], tuple[str, int] | None] = {}
    stratum = 0
    placements: list[Placement] = []
    untestable: list[str] = []
    for cell in grid:
        span = span_values(cell, window)
        if cell.group not in places:
            series_id = draw.choice(order)
            timeline = timelines[series_id]
            earliest = warmup + window
            latest = len(timeline.times) - 1 - span
            candidates = [
                index
                for index in range(earliest, latest + 1)
                if timeline.free(index, span)
            ]
            if not candidates:
                places[cell.group] = None
            else:
                # Stratified over the span: each tenth of it gets its share.
                size = len(candidates)
                low = stratum * size // STRATA
                high = max(low + 1, (stratum + 1) * size // STRATA)
                stratum = (stratum + 1) % STRATA
                places[cell.group] = (series_id, candidates[draw.randrange(low, high)])
        found = places[cell.group]
        if found is None:
            untestable.append(cell.id)
            continue
        series_id, start = found
        placements.append(
            _placement(cell, timelines[series_id], order, start, window, draw)
        )
    return placements, sorted(set(untestable))


def _placement(
    cell: Cell,
    timeline: Timeline,
    order: Sequence[str],
    start: int,
    window: int,
    draw: random.Random,
) -> Placement:
    family = cell.family
    times = timeline.times
    if family.kind == "spike":
        hold = 1
        end_at = _moment(times[start] + (times[start + 1] - times[start]) / 2)
    else:
        hold = hold_values(cell.length, window)
        end_at = _moment(times[start + hold - 1])
    start_at = _moment(times[start])
    if end_at <= start_at:
        end_at = start_at + timedelta(microseconds=1)
    fields: dict = {}
    if family.measure == "sigmas":
        fields["sigmas"] = (cell.level or 1.0) * draw.choice((-1.0, 1.0))
    if family.kind == "noise":
        fields["noise_factor"] = cell.level
        fields["seed"] = draw.randrange(1 << 30)
    if family.stuck is not None:
        fields["value"] = family.stuck
    if family.kind in ("step", "drift", "gain"):
        if family.onset == "slow":
            fields["onset_seconds"] = (end_at - start_at).total_seconds()
        elif family.kind == "drift":
            fields["onset_seconds"] = 0.0
        fields["recovery"] = family.recovery
        if family.recovery == "gradual":
            fields["recovery_seconds"] = max((end_at - start_at).total_seconds(), 1e-3)
    recovery = hold if family.recovery == "gradual" else 0
    cut_index = min(start + hold + recovery + 2 * window, len(times) - 1)
    fault = Fault(
        kind=family.kind,
        series_id=timeline.series_id,
        with_series=[item for item in order if item != timeline.series_id]
        if family.common
        else [],
        start_at=start_at,
        end_at=end_at,
        **fields,
    )
    return Placement(cell, timeline.series_id, start, fault, _moment(times[cut_index]))


def simple_rules(
    values: Sequence[tuple[float, float]],
    onset: float,
    label_end: float,
    sigma: float | None,
    window: int,
) -> bool:
    """Whether trivial rules catch the fault: a value 4σ from the median of the
    W values before it, 10 identical values in a row, or no value for 5
    typical intervals, inside the label (or at the first value after a gap)."""
    before = [value for moment, value in values if moment < onset][-window:]
    during = [(moment, value) for moment, value in values if onset <= moment]
    inside = [(moment, value) for moment, value in during if moment <= label_end]
    if before and sigma:
        centre = median(before)
        if any(abs(value - centre) > RULE_SIGMAS * sigma for _, value in inside):
            return True
    run = 1
    for (_, previous), (_, value) in pairwise(inside):
        run = run + 1 if value == previous else 1
        if run >= RULE_REPEATS:
            return True
    moments = [moment for moment, _ in values]
    steps = [b - a for a, b in pairwise(moments)]
    if steps:
        typical = median(steps)
        for (moment, _), step in zip(values[1:], steps, strict=False):
            if onset <= moment <= label_end and step > GAP_FACTOR * typical:
                return True
    return False


# Scoring


def wilson(caught: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
    """The 95% Wilson score interval of a catch rate."""
    if not total:
        return None
    rate = caught / total
    centre = (rate + z * z / (2 * total)) / (1 + z * z / total)
    half = (
        z
        * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total))
        / (1 + z * z / total)
    )
    return max(0.0, centre - half), min(1.0, centre + half)


def monotone(rates: Sequence[float], weights: Sequence[int]) -> list[float]:
    """Pool adjacent violators: the closest non-decreasing rates."""
    blocks: list[list[float]] = []
    for rate, weight in zip(rates, weights, strict=True):
        blocks.append([rate * weight, float(weight), 1])
        while len(blocks) > 1 and (
            blocks[-2][0] / max(blocks[-2][1], 1e-12)
            > blocks[-1][0] / max(blocks[-1][1], 1e-12)
        ):
            total, weight_sum, count = blocks.pop()
            blocks[-1][0] += total
            blocks[-1][1] += weight_sum
            blocks[-1][2] += count
    fitted = []
    for total, weight_sum, count in blocks:
        fitted.extend([total / max(weight_sum, 1e-12)] * int(count))
    return fitted


def crossing(
    levels: Sequence[float], rates: Sequence[float], target: float
) -> float | None:
    """The level at which a non-decreasing rate first reaches ``target``,
    interpolated along log2 of the level; None if it never does."""
    for index, rate in enumerate(rates):
        if rate >= target:
            if index == 0:
                return levels[0]
            low, high = rates[index - 1], rate
            share = (target - low) / (high - low) if high > low else 1.0
            a, b = math.log2(levels[index - 1]), math.log2(levels[index])
            return 2 ** (a + share * (b - a))
    return None


@dataclass(frozen=True)
class Planted:
    """One planted fault of a study, as its copy and its run saw it."""

    family: str
    title: str
    measure: Measure
    level: float | None
    sanity: bool
    outcome: LabelOutcome | None
    confounded: bool
    simple_rules: bool
    onset_seconds: float
    sigmas: float | None


def report(
    protocol: dict,
    clean: RunMetrics | None,
    clean_run_id: str | None,
    planted: Sequence[Planted],
) -> ProtocolReport:
    share = clean.alarm_share if clean else None
    per_day = clean.false_alarms_per_day if clean else None
    within = None
    if clean is not None and share is not None:
        within = (per_day or 0.0) <= BUDGET_PER_DAY and share <= BUDGET_SHARE
    families: dict[str, list[Planted]] = {}
    for item in planted:
        families.setdefault(item.family, []).append(item)
    profiles = [_family(items, share) for items in families.values()]
    realistic = [
        item.adjusted_detection_rate
        for item in profiles
        if item.adjusted_detection_rate is not None and not item.sanity
    ]
    sanity = [item for item in planted if item.sanity]
    sanity_missed = sum(
        1 for item in sanity if item.outcome and item.outcome.outcome == "missed"
    )
    result = ProtocolReport(
        protocol=protocol.get("name", ""),
        version=protocol.get("version", VERSION),
        purpose=protocol.get("purpose", "practice"),
        seed=protocol.get("seed"),
        warmup_values=protocol.get("warmup_values"),
        window_values=protocol.get("window_values"),
        clean_run_id=clean_run_id,
        false_alarms_per_day=per_day,
        alarm_share=share,
        budget_per_day=BUDGET_PER_DAY,
        budget_share=BUDGET_SHARE,
        within_budget=within,
        adjusted_detection_rate=(
            sum(realistic) / len(realistic) if realistic else None
        ),
        faults=len(planted),
        caught=sum(1 for item in planted if _caught(item)),
        simple_rules_caught=sum(1 for item in planted if item.simple_rules),
        sanity_missed=sanity_missed,
        untestable=protocol.get("untestable", []),
        families=profiles,
        headline="",
    )
    return result.model_copy(update={"headline": headline(result)})


def _caught(item: Planted) -> bool:
    return (
        item.outcome is not None
        and item.outcome.outcome == "detected"
        and not item.confounded
    )


def _family(items: Sequence[Planted], share: float | None) -> ProtocolFamily:
    first = items[0]
    by_level: dict[float | None, list[Planted]] = {}
    for item in items:
        by_level.setdefault(item.level, []).append(item)
    levels = []
    for level in sorted(by_level, key=lambda value: -1 if value is None else value):
        group = by_level[level]
        scored = [
            item
            for item in group
            if item.outcome is not None
            and item.outcome.outcome != "unscored"
            and not item.confounded
        ]
        caught = sum(1 for item in scored if _caught(item))
        interval = wilson(caught, len(scored))
        levels.append(
            ProtocolLevel(
                level=level,
                faults=len(group),
                scored=len(scored),
                caught=caught,
                confounded=sum(1 for item in group if item.confounded),
                rate=caught / len(scored) if scored else None,
                low=interval[0] if interval else None,
                high=interval[1] if interval else None,
                simple_rules=sum(1 for item in group if item.simple_rules),
            )
        )
    scored = [
        item
        for item in items
        if item.outcome is not None
        and item.outcome.outcome != "unscored"
        and not item.confounded
    ]
    caught = sum(1 for item in scored if _caught(item))
    chance = sum(
        item.outcome.chance or 0.0
        for item in scored
        if item.outcome is not None and share is not None
    )
    adjusted = None
    if share is not None and len(scored) - chance > 1e-9:
        adjusted = (caught - chance) / (len(scored) - chance)
    half = ninety = None
    sized = [
        item for item in levels if item.level is not None and item.rate is not None
    ]
    if first.measure in ("sigmas", "factor") and sized:
        fitted = monotone(
            [item.rate or 0.0 for item in sized], [item.scored for item in sized]
        )
        marks = [item.level or 1.0 for item in sized]
        half = crossing(marks, fitted, 0.5)
        ninety = crossing(marks, fitted, 0.9)
    delays = [
        item.outcome.delay_seconds
        for item in items
        if _caught(item) and item.outcome and item.outcome.delay_seconds is not None
    ]
    reached = [
        abs(item.sigmas)
        * min(1.0, (item.outcome.delay_seconds or 0) / item.onset_seconds)
        for item in items
        if _caught(item)
        and item.outcome
        and item.sigmas is not None
        and item.onset_seconds > 0
    ]
    return ProtocolFamily(
        family=first.family,
        title=first.title,
        measure=first.measure,
        sanity=first.sanity,
        faults=len(items),
        scored=len(scored),
        caught=caught,
        chance_detections=chance if share is not None else None,
        adjusted_detection_rate=adjusted,
        half=half,
        ninety=ninety,
        median_delay_seconds=median(delays) if delays else None,
        median_sigmas_at_detection=median(reached) if reached else None,
        simple_rules_caught=sum(1 for item in items if item.simple_rules),
        levels=levels,
    )


def _amount(family: ProtocolFamily, value: float) -> str:
    if family.measure == "sigmas":
        return f"{value:.2g}σ"
    return f"×{value:.2g}"


def _budget(report: ProtocolReport) -> str:
    if report.within_budget is None:
        return "no clean run to judge false alarms by"
    rate = report.false_alarms_per_day or 0.0
    verdict = "within" if report.within_budget else "over"
    return (
        f"{rate:.2g} false alarms a day and {100 * (report.alarm_share or 0):.2g}% "
        f"of the time in alarm on the clean copy, {verdict} the budget of "
        f"{report.budget_per_day:g} a day and {100 * report.budget_share:g}%"
    )


def _verdicts(report: ProtocolReport) -> tuple[list[str], list[str]]:
    caught, missed = [], []
    for family in report.families:
        name = family.title.lower()
        if family.sanity or not family.scored:
            continue
        if family.measure in ("sigmas", "factor"):
            if family.half is not None:
                caught.append(f"{name} from {_amount(family, family.half)}")
            else:
                top = max((item.level or 0 for item in family.levels), default=0)
                missed.append(f"{name} up to {_amount(family, top)}")
        elif family.caught:
            caught.append(f"{name} {family.caught} of {family.scored}")
        else:
            missed.append(name)
    return caught, missed


def headline(report: ProtocolReport) -> str:
    """The sentence a proposal carries: budget first, then each family."""
    parts = [_budget(report)]
    caught, missed = _verdicts(report)
    if caught:
        parts.append("catches " + ", ".join(caught))
    if missed:
        parts.append("does not catch " + ", ".join(missed))
    parts.append(f"simple rules catch {report.simple_rules_caught} of {report.faults}")
    if report.sanity_missed:
        parts.append(f"misses {report.sanity_missed} impossible values, a bug")
    if report.untestable:
        parts.append(f"{len(report.untestable)} faults did not fit the history")
    text = "; ".join(parts)
    return text[0].upper() + text[1:] + "."
