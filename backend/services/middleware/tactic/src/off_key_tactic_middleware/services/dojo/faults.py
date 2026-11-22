"""Write known problems into a copy of a Dojo dataset, each one labelled.

A design tested on the copy shows whether it catches a step, a drift, a gain
error, rising noise, a spike, a frozen value, a gap or an impossible value,
and how late: the run's metrics score it against the labels.

Sizes are measured in the series' short-term noise: the spread of one value
to the next, which level changes and daily cycles barely move, unlike the
spread of the whole series.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from off_key_core.db.models import DojoLabel, DojoPoint, DojoSeries
from off_key_core.schemas.dojo import MAX_DATASET_LABELS, Fault
from sqlalchemy import (
    BigInteger,
    Float,
    Text,
    and_,
    case,
    cast,
    extract,
    func,
    literal,
    not_,
    or_,
    select,
    true,
)
from sqlalchemy.dialects.postgresql import BIT

from ...domain import ValidationError

# A step, drift, gain or spike left without a size moves the values this many
# times the short-term noise of the series.
DEFAULT_SIGMAS = 3.0
DEFAULT_NOISE_FACTOR = 3.0
# Half the spread of differences of independent values, robustly: the median
# absolute difference times 1.4826 estimates the standard deviation of a
# difference, which is sqrt(2) times that of one value.
MAD_SCALE = 1.4826 / math.sqrt(2)
# An impossible value lies this many recorded ranges beyond the largest value.
OUT_OF_RANGE_RANGES = 10.0


async def noise_sigma(session, series_id: str) -> float | None:
    """The short-term noise of a series: a robust spread of its differences."""
    step = (
        select(
            func.abs(
                DojoPoint.value
                - func.lag(DojoPoint.value).over(order_by=DojoPoint.timestamp)
            ).label("change")
        )
        .where(DojoPoint.series_id == series_id)
        .subquery()
    )
    middle = await session.scalar(
        select(func.percentile_cont(0.5).within_group(step.c.change)).where(
            step.c.change.is_not(None)
        )
    )
    return None if middle is None else float(middle) * MAD_SCALE


@dataclass(frozen=True)
class Target:
    """What one fault writes into one series."""

    series: DojoSeries
    sigma: float | None = None
    size: float | None = None
    gain: float | None = None
    amplitude: float | None = None
    frozen: float | None = None
    first: datetime | None = None
    # The last moment the fault changes values; a gap is noticed at the first
    # value after it, so its label runs there.
    label_end: datetime | None = None


@dataclass(frozen=True)
class PlannedFault:
    fault: Fault
    targets: list[Target] = field(default_factory=list)

    @property
    def onset(self) -> float:
        if self.fault.kind == "drift" and self.fault.onset_seconds is None:
            return (self.fault.end_at - self.fault.start_at).total_seconds()
        return self.fault.onset_seconds or 0.0

    @property
    def recovery(self) -> float:
        if self.fault.recovery != "gradual":
            return 0.0
        if self.fault.recovery_seconds is not None:
            return self.fault.recovery_seconds
        return self.onset or (self.fault.end_at - self.fault.start_at).total_seconds()

    @property
    def interval(self) -> tuple[datetime, datetime]:
        ends = [item.label_end for item in self.targets if item.label_end]
        return self.fault.start_at, max([self.fault.end_at, *ends])

    @property
    def sigmas(self) -> float | None:
        """The size in short-term noise, as its first series measures it."""
        first = self.targets[0]
        if first.size is None or not first.sigma:
            return None
        return first.size / first.sigma

    def note(self) -> str:
        first = self.targets[0]
        unit = f" {first.series.unit}" if first.series.unit else ""
        names = ", ".join(item.series.name for item in self.targets)
        kind = self.fault.kind
        sigmas = self.sigmas
        size = f"{first.size:+.4g}{unit}" if first.size is not None else ""
        if sigmas is not None:
            size += f" ({sigmas:+.2g}σ)"
        if kind == "step":
            what = f"step of {size}"
        elif kind == "drift":
            what = f"drift to {size}"
        elif kind == "gain":
            what = f"gain error moving a typical value by {size}"
        elif kind == "spike":
            what = f"spike of {size}"
        elif kind == "noise":
            factor = self.fault.noise_factor or DEFAULT_NOISE_FACTOR
            what = f"noise ×{factor:.3g}"
        elif kind == "freeze":
            what = f"freeze at {first.frozen:.4g}{unit}"
        elif kind == "out_of_range":
            what = f"out-of-range value {first.frozen:.4g}{unit}"
        else:
            what = "gap"
        return f"Injected {what} on {names}{self._shape()}"

    def _shape(self) -> str:
        """The onset and recovery, where they differ from the kind's own."""
        parts = []
        explicit = self.fault.onset_seconds is not None
        if self.fault.kind in ("step", "gain") and self.onset:
            parts.append(f"onset over {duration(self.onset)}")
        elif self.fault.kind == "drift" and explicit:
            parts.append(
                f"onset over {duration(self.onset)}" if self.onset else "sudden onset"
            )
        if self.fault.recovery == "none":
            parts.append("no recovery")
        elif self.fault.recovery == "gradual":
            parts.append(f"recovering over {duration(self.recovery)}")
        return "".join(f", {part}" for part in parts)


def duration(seconds: float) -> str:
    """A length of time as people say it."""
    if seconds < 120:
        return f"{seconds:.3g} s"
    if seconds < 7200:
        return f"{seconds / 60:.3g} min"
    if seconds < 172_800:
        return f"{seconds / 3600:.3g} h"
    return f"{seconds / 86_400:.3g} d"


def _epoch(moment):
    return cast(extract("epoch", moment), Float)


def _inside(item: PlannedFault, target: Target):
    start, end = item.fault.start_at, item.fault.end_at
    if item.fault.kind in ("step", "drift", "gain") and target.label_end:
        end = target.label_end
    if item.fault.kind == "spike":
        return DojoPoint.timestamp == target.first
    return and_(DojoPoint.timestamp >= start, DojoPoint.timestamp <= end)


def _envelope(item: PlannedFault):
    """From 0 to 1 over the onset, 1 while held, back to 0 over the recovery."""
    fault = item.fault
    now = _epoch(DojoPoint.timestamp)
    start = fault.start_at.timestamp()
    end = fault.end_at.timestamp()
    branches = []
    if item.onset:
        branches.append(
            (
                DojoPoint.timestamp < fault.start_at + timedelta(seconds=item.onset),
                (now - start) / item.onset,
            )
        )
    branches.append((DojoPoint.timestamp <= fault.end_at, literal(1.0, Float)))
    if fault.recovery == "gradual":
        branches.append(
            (
                DojoPoint.timestamp < fault.end_at + timedelta(seconds=item.recovery),
                1 - (now - end) / item.recovery,
            )
        )
    tail = 1.0 if fault.recovery == "none" else 0.0
    return case(*branches, else_=literal(tail, Float))


def _uniform(seed: int, salt: str, series_id: str):
    """A draw in (0, 1) fixed by the seed, the series and the timestamp."""
    digest = func.md5(
        func.concat(
            f"{seed}:{salt}:{series_id}:", cast(_epoch(DojoPoint.timestamp), Text)
        )
    )
    bits = cast(func.concat("x", func.substr(digest, 1, 8)), BIT(32))
    return (cast(cast(bits, BigInteger), Float) + 0.5) / 4294967296.0


def _changed(item: PlannedFault, target: Target):
    kind = item.fault.kind
    if kind in ("step", "drift"):
        return DojoPoint.value + target.size * _envelope(item)
    if kind == "gain":
        return DojoPoint.value * (1 + target.gain * _envelope(item))
    if kind == "spike":
        return DojoPoint.value + target.size
    if kind == "noise":
        seed, series = item.fault.seed, target.series.id
        normal = func.sqrt(-2 * func.ln(_uniform(seed, "a", series))) * func.cos(
            2 * math.pi * _uniform(seed, "b", series)
        )
        return DojoPoint.value + target.amplitude * normal
    return literal(target.frozen, Float)


def _of(planned: Sequence[PlannedFault], series_id: str):
    return [
        (item, target)
        for item in planned
        for target in item.targets
        if target.series.id == series_id
    ]


def written_value(planned: Sequence[PlannedFault], series_id: str):
    """Each value of a series as the copy holds it."""
    branches = [
        (_inside(item, target), _changed(item, target))
        for item, target in _of(planned, series_id)
        if item.fault.kind != "gap"
    ]
    return case(*branches, else_=DojoPoint.value) if branches else DojoPoint.value


def kept(planned: Sequence[PlannedFault], series_id: str, end_at: datetime | None):
    """Whether a value survives the gaps of its series and the copy's end."""
    gaps = [
        _inside(item, target)
        for item, target in _of(planned, series_id)
        if item.fault.kind == "gap"
    ]
    condition = not_(or_(*gaps)) if gaps else true()
    if end_at is not None:
        condition = and_(condition, DojoPoint.timestamp <= end_at)
    return condition


async def plan_faults(
    session,
    faults: Sequence[Fault],
    series: Mapping[str, DojoSeries],
    labels: Sequence[DojoLabel],
    end_at: datetime | None = None,
) -> list[PlannedFault]:
    """Check every fault against the dataset and settle what it writes."""
    if len(labels) + len(faults) > MAX_DATASET_LABELS:
        raise ValidationError(
            f"A dataset holds at most {MAX_DATASET_LABELS} labels; it has "
            f"{len(labels)}, so add at most {MAX_DATASET_LABELS - len(labels)} faults"
        )
    planned = []
    for number, fault in enumerate(faults, start=1):
        targets = []
        for series_id in [fault.series_id, *fault.with_series]:
            target = series.get(series_id)
            if target is None:
                raise ValidationError(
                    f"Fault {number}: the dataset has no series {series_id!r}"
                )
            targets.append(target)
        if end_at is not None and fault.start_at >= end_at:
            raise ValidationError(f"Fault {number} starts after the copy ends")
        item = PlannedFault(fault)
        planned.append(
            PlannedFault(
                fault,
                [
                    await _plan(session, number, item, target, end_at)
                    for target in targets
                ],
            )
        )
    _check_overlaps(planned, labels)
    return planned


async def _plan(
    session, number: int, item: PlannedFault, series: DojoSeries, cut
) -> Target:
    fault = item.fault
    of_series = DojoPoint.series_id == series.id
    within = and_(
        of_series,
        DojoPoint.timestamp >= fault.start_at,
        DojoPoint.timestamp <= fault.end_at,
    )
    inside = await session.scalar(select(func.count()).where(within))
    if not inside:
        raise ValidationError(
            f"Fault {number}: {series.name} holds no values from "
            f"{fault.start_at.isoformat()} to {fault.end_at.isoformat()}"
        )
    if fault.kind in ("step", "drift", "gain", "spike", "noise"):
        label_end = await _label_end(session, item, of_series, cut)
        return await _plan_sized(session, number, item, series, within, label_end)
    if fault.kind == "freeze":
        frozen = fault.value
        if frozen is None:
            frozen = await session.scalar(
                select(DojoPoint.value)
                .where(of_series, DojoPoint.timestamp < fault.start_at)
                .order_by(DojoPoint.timestamp.desc())
                .limit(1)
            )
        if frozen is None:
            frozen = await session.scalar(
                select(DojoPoint.value)
                .where(within)
                .order_by(DojoPoint.timestamp)
                .limit(1)
            )
        return Target(series, frozen=frozen)
    if fault.kind == "out_of_range":
        return Target(series, frozen=await _impossible(session, fault, of_series))
    after = await session.scalar(
        select(func.min(DojoPoint.timestamp)).where(
            of_series, DojoPoint.timestamp > fault.end_at
        )
    )
    return Target(series, label_end=after)


async def _label_end(session, item: PlannedFault, of_series, cut):
    """Where a level fault's label ends: after its recovery, or with the copy."""
    fault = item.fault
    if fault.recovery == "gradual":
        return fault.end_at + timedelta(seconds=item.recovery)
    if fault.recovery != "none":
        return None
    last = await session.scalar(
        select(func.max(DojoPoint.timestamp)).where(
            of_series, DojoPoint.timestamp <= cut if cut else true()
        )
    )
    return max(last, fault.end_at) if last else fault.end_at


async def _plan_sized(
    session, number: int, item: PlannedFault, series: DojoSeries, within, label_end
) -> Target:
    fault = item.fault
    sigma = await noise_sigma(session, series.id)
    if fault.kind == "noise":
        if not sigma:
            raise ValidationError(f"Fault {number}: {series.name} has no noise to grow")
        factor = fault.noise_factor or DEFAULT_NOISE_FACTOR
        return Target(
            series,
            sigma=sigma,
            amplitude=sigma * math.sqrt(factor**2 - 1),
            label_end=label_end,
        )
    size = fault.size
    if size is None:
        if not sigma:
            raise ValidationError(
                f"Fault {number}: {series.name} does not vary from one "
                "value to the next, so give a size"
            )
        size = (fault.sigmas or DEFAULT_SIGMAS) * sigma
    if fault.kind == "spike":
        first = await session.scalar(
            select(func.min(DojoPoint.timestamp)).where(within)
        )
        return Target(series, sigma=sigma, size=size, first=first)
    if fault.kind != "gain":
        return Target(series, sigma=sigma, size=size, label_end=label_end)
    typical = await session.scalar(
        select(func.percentile_cont(0.5).within_group(func.abs(DojoPoint.value))).where(
            DojoPoint.series_id == series.id
        )
    )
    if not typical:
        raise ValidationError(
            f"Fault {number}: a typical value of {series.name} is 0, which a "
            "gain error leaves unchanged"
        )
    return Target(
        series, sigma=sigma, size=size, gain=size / float(typical), label_end=label_end
    )


async def _impossible(session, fault: Fault, of_series) -> float:
    """A value far beyond anything the series recorded, unless one is given."""
    if fault.value is not None:
        return fault.value
    low, high = (
        await session.execute(
            select(func.min(DojoPoint.value), func.max(DojoPoint.value)).where(
                of_series
            )
        )
    ).one()
    spread = (high - low) or max(abs(high), 1.0)
    return high + OUT_OF_RANGE_RANGES * spread


def _check_overlaps(
    planned: Sequence[PlannedFault], labels: Sequence[DojoLabel]
) -> None:
    """Labels of one dataset never overlap, so neither may the faults."""
    taken = [
        (label.start_at, label.end_at, f"the label from {label.start_at.isoformat()}")
        for label in labels
    ]
    for number, item in enumerate(planned, start=1):
        start, end = item.interval
        for other_start, other_end, name in taken:
            if start < other_end and end > other_start:
                raise ValidationError(
                    f"Fault {number} overlaps {name}; each fault becomes a "
                    "label, and labels of one dataset may not overlap"
                )
        taken.append((start, end, f"fault {number}"))
