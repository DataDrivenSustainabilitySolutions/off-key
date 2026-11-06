"""Translate catalogue devices and readings to recorded identities and back.

Measurements and evidence are stored by entity and reading key. A reading of a
device records under that device's entity; a reading without a device records
under its broker's.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from off_key_core.schemas.system import SystemDevice, SystemSnapshot, SystemStream

from ...domain import NotFoundError

RecordedScope = dict[str, frozenset[str]]


class CatalogueIds:
    def __init__(self, snapshot: SystemSnapshot):
        document = snapshot.document
        bindings: Mapping[str, Mapping[str, Any]] = snapshot.runtime.bindings
        self._streams = {stream.id: stream for stream in document.streams}
        self._devices = {device.id: device for device in document.devices}
        self._recorded = {
            stream_id: (binding["entity_id"], binding["telemetry_key"])
            for stream_id, binding in bindings.items()
            if stream_id in self._streams
        }
        self._readings = {pair: stream_id for stream_id, pair in self._recorded.items()}

    def recorded(self, stream_id: str) -> tuple[str, str]:
        """The entity and key a catalogue reading records under."""
        try:
            return self._recorded[stream_id]
        except KeyError:
            raise NotFoundError("Reading not found") from None

    def device(self, device_id: str) -> SystemDevice:
        try:
            return self._devices[device_id]
        except KeyError:
            raise NotFoundError("Device not found") from None

    def devices(self) -> list[SystemDevice]:
        return list(self._devices.values())

    def device_streams(self, device_id: str) -> list[SystemStream]:
        self.device(device_id)
        return [
            stream for stream in self._streams.values() if stream.device_id == device_id
        ]

    def scope(self, stream_ids: Iterable[str]) -> RecordedScope:
        """Recorded keys of these readings, by entity."""
        keys: dict[str, set[str]] = {}
        for stream_id in stream_ids:
            entity, key = self.recorded(stream_id)
            keys.setdefault(entity, set()).add(key)
        return {entity: frozenset(found) for entity, found in keys.items()}

    def device_scope(self, device_id: str) -> RecordedScope:
        """Recorded keys of every reading of a device that records yet."""
        return self.scope(
            stream.id
            for stream in self.device_streams(device_id)
            if stream.id in self._recorded
        )

    def stream_ids(self, entity: str, keys: Iterable[str]) -> list[str]:
        """The catalogue readings behind recorded keys; unknown keys are left out."""
        found = (self._readings.get((entity, key)) for key in keys)
        return [stream_id for stream_id in found if stream_id is not None]

    def device_id(self, stream_ids: Iterable[str]) -> str | None:
        for stream_id in stream_ids:
            return self._streams[stream_id].device_id
        return None
