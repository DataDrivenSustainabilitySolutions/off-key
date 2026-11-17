"""Write known problems into a copy of a Dojo dataset, each one labelled.

A design tested on the copy shows whether it catches a step, a drift, a frozen
value or a gap, and how late: the run's metrics score it against the labels.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from off_key_core.db.models import DojoLabel, DojoPoint, DojoSeries
from off_key_core.schemas.dojo import MAX_DATASET_LABELS, Fault
from sqlalchemy import (
    Float,
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

from ...domain import ValidationError

# A step or a drift left without a size moves the values this many standard
# deviations of the series, enough to stand out from ordinary variation.
STANDARD_DEVIATIONS = 3.0


@dataclass(frozen=True)
class PlannedFault:
    fault: Fault
    series: DojoSeries
    size: float | None = None
    frozen: float | None = None
    # A gap is noticed at the first value after it, so its label runs there.
    label_end: datetime | None = None

    @property
    def interval(self) -> tuple[datetime, datetime]:
        return self.fault.start_at, self.label_end or self.fault.end_at

    def note(self) -> str:
        name = self.series.name
        unit = f" {self.series.unit}" if self.series.unit else ""
        if self.fault.kind == "step":
            return f"Injected step of {self.size:+.4g}{unit} on {name}"
        if self.fault.kind == "drift":
            return f"Injected drift to {self.size:+.4g}{unit} on {name}"
        if self.fault.kind == "freeze":
            return f"Injected freeze at {self.frozen:.4g}{unit} on {name}"
        return f"Injected gap on {name}"


def _inside(fault: Fault):
    return and_(
        DojoPoint.timestamp >= fault.start_at, DojoPoint.timestamp <= fault.end_at
    )


def _changed(item: PlannedFault):
    fault = item.fault
    if fault.kind == "step":
        return DojoPoint.value + item.size
    if fault.kind == "drift":
        start = fault.start_at.timestamp()
        share = (cast(extract("epoch", DojoPoint.timestamp), Float) - start) / (
            fault.end_at.timestamp() - start
        )
        return DojoPoint.value + share * item.size
    return literal(item.frozen, Float)


def written_value(planned: Sequence[PlannedFault]):
    """Each value of a series as the copy holds it."""
    branches = [
        (_inside(item.fault), _changed(item))
        for item in planned
        if item.fault.kind != "gap"
    ]
    return case(*branches, else_=DojoPoint.value) if branches else DojoPoint.value


def kept(planned: Sequence[PlannedFault]):
    """Whether a value survives the gaps of its series."""
    gaps = [_inside(item.fault) for item in planned if item.fault.kind == "gap"]
    return not_(or_(*gaps)) if gaps else true()


async def plan_faults(
    session,
    faults: Sequence[Fault],
    series: Mapping[str, DojoSeries],
    labels: Sequence[DojoLabel],
) -> list[PlannedFault]:
    """Check every fault against the dataset and settle what it writes."""
    if len(labels) + len(faults) > MAX_DATASET_LABELS:
        raise ValidationError(
            f"A dataset holds at most {MAX_DATASET_LABELS} labels; it has "
            f"{len(labels)}, so add at most {MAX_DATASET_LABELS - len(labels)} faults"
        )
    planned = []
    for number, fault in enumerate(faults, start=1):
        target = series.get(fault.series_id)
        if target is None:
            raise ValidationError(
                f"Fault {number}: the dataset has no series {fault.series_id!r}"
            )
        planned.append(await _plan(session, number, fault, target))
    _check_overlaps(planned, labels)
    return planned


async def _plan(session, number: int, fault: Fault, series: DojoSeries):
    of_series = DojoPoint.series_id == series.id
    inside = await session.scalar(select(func.count()).where(of_series, _inside(fault)))
    if not inside:
        raise ValidationError(
            f"Fault {number}: {series.name} holds no values from "
            f"{fault.start_at.isoformat()} to {fault.end_at.isoformat()}"
        )
    if fault.kind in ("step", "drift"):
        size = fault.size
        if size is None:
            spread = await session.scalar(
                select(func.stddev_samp(DojoPoint.value)).where(of_series)
            )
            if not spread:
                raise ValidationError(
                    f"Fault {number}: {series.name} does not vary, so give a size"
                )
            size = STANDARD_DEVIATIONS * spread
        return PlannedFault(fault, series, size=size)
    if fault.kind == "freeze":
        before = await session.scalar(
            select(DojoPoint.value)
            .where(of_series, DojoPoint.timestamp < fault.start_at)
            .order_by(DojoPoint.timestamp.desc())
            .limit(1)
        )
        if before is None:
            before = await session.scalar(
                select(DojoPoint.value)
                .where(of_series, _inside(fault))
                .order_by(DojoPoint.timestamp)
                .limit(1)
            )
        return PlannedFault(fault, series, frozen=before)
    after = await session.scalar(
        select(func.min(DojoPoint.timestamp)).where(
            of_series, DojoPoint.timestamp > fault.end_at
        )
    )
    return PlannedFault(fault, series, label_end=after)


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
