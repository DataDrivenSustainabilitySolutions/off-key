"""Which alarms a reporting query selects, in recorded identities."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ReadingScope:
    """Recorded readings an alarm must touch to be reported.

    `whole_entities` are entities whose every reading is in scope: a
    multivariate alarm without a sensor set cannot say which readings it used,
    so it is only shown when nothing of its entity is left out.
    """

    pairs: frozenset[tuple[str, str]]
    whole_entities: frozenset[str] = frozenset()

    @property
    def entities(self) -> frozenset[str]:
        return frozenset(entity for entity, _ in self.pairs)


@dataclass(frozen=True)
class AnomalyFilters:
    scope: ReadingScope | None = None
    reading: ReadingScope | None = None
    service_id: str | None = None
    since: datetime | None = None
    until: datetime | None = None
    max_p_value: float | None = None
