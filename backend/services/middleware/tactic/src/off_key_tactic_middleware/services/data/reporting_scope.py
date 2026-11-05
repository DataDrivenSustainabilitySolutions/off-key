"""Translate catalogue readings to the identities alarms are stored under."""

from collections.abc import Iterable, Mapping
from typing import Any

from off_key_core.schemas.system import SystemDocument

from ...repositories.anomaly_filters import ReadingScope


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


class CatalogueLabels:
    """Catalogue names for recorded identities, falling back to the identity
    when the catalogue no longer has it."""

    def __init__(
        self, document: SystemDocument, bindings: Mapping[str, Mapping[str, Any]]
    ):
        connections = {item.id: item.label for item in document.connections}
        devices = {item.id: item.label for item in document.devices}
        self._entities: dict[str, str] = {}
        self._readings: dict[tuple[str, str], str] = {}
        for stream in document.streams:
            binding = bindings.get(stream.id)
            if binding is None:
                continue
            entity = binding["entity_id"]
            owner = (
                stream.device_id and devices.get(stream.device_id)
            ) or connections.get(stream.connection_id)
            if owner:
                self._entities.setdefault(entity, owner)
            self._readings[(entity, binding["telemetry_key"])] = stream.label

    def entity(self, entity_id: str) -> str:
        return self._entities.get(entity_id, entity_id)

    def reading(self, entity_id: str, key: str) -> str:
        return self._readings.get((entity_id, key), key)
