"""How long a reading's gaps usually get, so quiet spells are not reported idle."""

from collections import deque
from math import ceil

GAPS = 50
QUANTILE = 0.9


class ArrivalCadence:
    """The 90th percentile of a reading's recent gaps between fresh arrivals.

    A median follows the bursts of a sensor that reports on change, or the fast
    phase of one that slows down when idle, so its pauses look like outages. The
    upper tail learns those pauses while one rare outage still cannot dominate.
    """

    def __init__(self):
        self.last: float | None = None
        self.gaps: deque[float] = deque(maxlen=GAPS)

    def add(self, at: float) -> None:
        if self.last is not None and at > self.last:
            self.gaps.append(at - self.last)
        self.last = at

    @property
    def typical_seconds(self) -> float | None:
        if not self.gaps:
            return None
        ordered = sorted(self.gaps)
        return round(ordered[ceil(QUANTILE * len(ordered)) - 1], 3)
