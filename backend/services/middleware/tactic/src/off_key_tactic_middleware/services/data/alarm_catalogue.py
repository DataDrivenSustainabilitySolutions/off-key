"""Translate catalogue devices and readings to the identities alarms are stored
under, and stored alarms back to catalogue ids and names."""

from collections.abc import Iterable, Mapping
from typing import Any

from off_key_core.db.models import Anomaly
from off_key_core.schemas.alarms import (
    MULTIVARIATE_TELEMETRY_TYPE,
    Alarm,
    AlarmQuery,
    AlarmReadingCount,
)
from off_key_core.schemas.system import SystemSnapshot

from ...domain import ValidationError
from ...repositories.anomaly_filters import AnomalyFilters, ReadingScope
from .catalogue_ids import CatalogueIds


def reading_scope(
    bindings: Mapping[str, Mapping[str, Any]], stream_ids: Iterable[str]
) -> tuple[ReadingScope, list[str]]:
    """The scope of these catalogue readings, and the ids the catalogue lacks."""
    selected = set(stream_ids)
    pairs: set[tuple[str, str]] = set()
    whole: dict[str, bool] = {}
    for stream_id, binding in bindings.items():
        entity = binding["entity_id"]
        chosen = stream_id in selected
        whole[entity] = whole.get(entity, True) and chosen
        if chosen:
            pairs.add((entity, binding["telemetry_key"]))
    unknown = sorted(selected - bindings.keys())
    whole_entities = frozenset(entity for entity, every in whole.items() if every)
    return ReadingScope(frozenset(pairs), whole_entities), unknown


class AlarmCatalogue:
    """Catalogue ids and names for alarms stored by recorded identity.

    A reading of a device is recorded under that device's entity, a reading
    without a device under its broker's; an entity the catalogue no longer has
    reports no device.
    """

    def __init__(self, snapshot: SystemSnapshot):
        self._ids = CatalogueIds(snapshot)
        self._bindings: Mapping[str, Mapping[str, Any]] = snapshot.runtime.bindings
        document = snapshot.document
        brokers = {item.id: item.label for item in document.connections}
        devices = {item.id: item.label for item in document.devices}
        self._labels = {stream.id: stream.label for stream in document.streams}
        self._owners: dict[str, tuple[str | None, str | None]] = {}
        for stream in document.streams:
            binding = self._bindings.get(stream.id)
            if binding is None:
                continue
            device_id = stream.device_id if stream.device_id in devices else None
            label = (
                devices[device_id] if device_id else brokers.get(stream.connection_id)
            )
            self._owners.setdefault(binding["entity_id"], (device_id, label))

    def scope(self, stream_ids: Iterable[str]) -> tuple[ReadingScope, list[str]]:
        return reading_scope(self._bindings, stream_ids)

    def filters(self, query: AlarmQuery) -> tuple[AnomalyFilters, list[str]]:
        scope, unknown = (
            (None, []) if query.reading_ids is None else self.scope(query.reading_ids)
        )
        narrowing = (
            self.narrowing(query.reading_id) if query.reading_id is not None else None
        )
        if (
            query.reading_id is not None
            and narrowing is not None
            and not narrowing.pairs
        ):
            unknown = sorted({*unknown, query.reading_id})
        return AnomalyFilters(
            scope=scope,
            reading=narrowing,
            service_id=query.monitor_id,
            since=query.since,
            until=query.until,
            max_p_value=query.max_p_value,
        ), unknown

    def device_scope(self, device_id: str) -> ReadingScope:
        """Every reading of a device; 404 when the catalogue lacks the device."""
        scope, _ = self.scope(
            stream.id for stream in self._ids.device_streams(device_id)
        )
        return scope

    def narrowing(self, stream_id: str) -> ReadingScope:
        """One reading to narrow a query to; matches nothing when unknown."""
        scope, _ = self.scope([stream_id])
        return ReadingScope(scope.pairs)

    def recorded(self, stream_ids: Iterable[str]) -> tuple[str, list[str]]:
        """The entity and keys an alarm about these readings is stored under."""
        pairs = [
            self._ids.recorded(stream_id) for stream_id in dict.fromkeys(stream_ids)
        ]
        if len({entity for entity, _ in pairs}) > 1:
            raise ValidationError(
                "Name readings of one device, or of one broker without a device"
            )
        return pairs[0][0], [key for _, key in pairs]

    def alarm(self, alarm_id: str, row: Anomaly) -> Alarm:
        entity = row.charger_id
        multivariate = row.telemetry_type == MULTIVARIATE_TELEMETRY_TYPE
        keys = row.sensor_set or ([] if multivariate else [row.telemetry_type])
        reading_ids = list(dict.fromkeys(self._ids.stream_ids(entity, keys)))
        device_id, device_label = self._owners.get(entity, (None, None))
        return Alarm(
            alarm_id=str(alarm_id),
            timestamp=row.timestamp,
            device_id=device_id,
            device_label=device_label,
            reading_ids=reading_ids,
            reading_labels={id: self._labels[id] for id in reading_ids},
            multivariate=multivariate,
            alarm_type=row.anomaly_type,
            value=row.anomaly_value,
            value_type=row.value_type,
            monitor_id=row.service_id or None,
        )

    def reading_count(
        self, entity: str, key: str, count: int
    ) -> AlarmReadingCount | None:
        """Alarms of one recorded reading; None when the catalogue lacks it."""
        found = self._ids.stream_ids(entity, [key])
        if not found:
            return None
        device_id, device_label = self._owners.get(entity, (None, None))
        return AlarmReadingCount(
            reading_id=found[0],
            device_id=device_id,
            device_label=device_label,
            label=self._labels[found[0]],
            count=count,
        )
