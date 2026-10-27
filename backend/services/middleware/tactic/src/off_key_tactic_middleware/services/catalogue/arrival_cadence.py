"""How often a reading usually arrives, so slow sources are not reported idle."""

from collections import deque
from statistics import median

GAPS = 9


class ArrivalCadence:
    """The median of a reading's recent gaps between fresh arrivals.

    A median ignores the occasional outage or burst, so the typical interval
    stays the source's own reporting rhythm.
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
        return round(median(self.gaps), 3) if self.gaps else None
