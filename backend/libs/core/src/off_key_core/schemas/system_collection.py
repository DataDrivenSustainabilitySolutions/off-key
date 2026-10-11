"""Domain-neutral collection bindings and the explicit opt-in contract."""

import hashlib
from collections import Counter
from dataclasses import dataclass

from pydantic import Field

from .collection import AmbiboxCatalog, CollectionPolicy
from .system import EntityId, SystemDocument, SystemModel, SystemStream


def stable_key(kind: str, identity: str) -> str:
    return f"{kind}-{hashlib.sha256(identity.encode()).hexdigest()}"


class ReadingBinding(SystemModel):
    entity_id: str
    telemetry_key: str
    accepted_topic: str
    device_id: str | None = None


class SystemCollectionDefinition(SystemModel):
    document: SystemDocument
    bindings: dict[str, ReadingBinding]
    generation: str = "initial"

    @property
    def sources(self):
        return self.document.connections

    def streams(self, *, selected_only: bool = False) -> list:
        connections = {
            item.id: item.model_dump(exclude={"label"})
            for item in self.document.connections
        }
        return [
            SystemCollectionStream(
                stream,
                self.bindings[stream.id],
                stream.policy or self.document.default_policy,
                connections[stream.connection_id],
                self.generation,
            )
            for stream in self.document.streams
            if not selected_only
            or (stream.policy or self.document.default_policy).mode != "off"
        ]


@dataclass(frozen=True)
class SystemCollectionStream:
    definition: SystemStream
    binding: ReadingBinding
    policy: CollectionPolicy
    endpoint: dict
    generation: str

    @property
    def source_id(self):
        return self.definition.connection_id

    @property
    def charger_id(self):
        # Compatibility with existing history/evidence tables. Public catalogue
        # identities and upstream MQTT topics do not use the legacy domain model.
        return self.binding.entity_id

    @property
    def sensor(self):
        return self

    @property
    def key(self):
        return self.binding.telemetry_key

    @property
    def value_type(self):
        return self.definition.value_type

    @property
    def ingress_topic(self):
        key = stable_key("reading", self.definition.id)
        return f"ingress/system/{self.generation}/{key}"

    @property
    def accepted_topic(self):
        return self.binding.accepted_topic

    @property
    def signature(self):
        return (
            stable_key("reading", self.definition.id),
            self.accepted_topic,
            self.definition.topic,
            self.definition.payload_pointer,
            self.value_type,
            self.policy.mode,
            self.policy.cadence,
            self.endpoint,
        )


def build_bindings(
    document: SystemDocument,
    legacy: AmbiboxCatalog,
    previous: dict[str, ReadingBinding] | None = None,
) -> dict[str, ReadingBinding]:
    """Keep historic IDs where the concrete input matches unambiguously."""
    legacy_connections = {str(source.id): source for source in legacy.sources}
    matches: dict[tuple, list] = {}
    for stream in legacy.streams():
        source = legacy_connections[stream.source_id]
        key = (
            source.host,
            source.port,
            stream.sensor.upstream_topic,
            stream.sensor.value_type,
        )
        matches.setdefault(key, []).append(stream)
    connections = {item.id: item for item in document.connections}
    inputs = Counter(
        (
            connections[item.connection_id].host,
            connections[item.connection_id].port,
            item.topic,
            item.value_type,
        )
        for item in document.streams
    )
    preserved_topics = {
        existing.accepted_topic
        for stream in document.streams
        if (existing := (previous or {}).get(stream.id))
        and existing.device_id == stream.device_id
    }
    result = {}
    for stream in document.streams:
        existing = (previous or {}).get(stream.id)
        if existing and existing.device_id == stream.device_id:
            result[stream.id] = existing
            continue
        connection = connections[stream.connection_id]
        candidates = matches.get(
            (connection.host, connection.port, stream.topic, stream.value_type), []
        )
        if (
            len(candidates) == 1
            and candidates[0].accepted_topic not in preserved_topics
            and inputs[
                (connection.host, connection.port, stream.topic, stream.value_type)
            ]
            == 1
            and not connection.tls
            and connection.transport == "tcp"
            and stream.payload_pointer is None
        ):
            candidate = candidates[0]
            result[stream.id] = ReadingBinding(
                entity_id=candidate.charger_id,
                telemetry_key=candidate.sensor.key,
                accepted_topic=candidate.accepted_topic,
                device_id=stream.device_id,
            )
        else:
            entity = stable_key("entity", stream.device_id or stream.connection_id)
            key = stable_key("reading", stream.id)
            result[stream.id] = ReadingBinding(
                entity_id=entity,
                telemetry_key=key,
                accepted_topic=f"telemetry/{entity}/{key}",
                device_id=stream.device_id,
            )
    return result


def runtime_fingerprint(catalog) -> list:
    if isinstance(catalog, AmbiboxCatalog):
        endpoints = {str(item.id): (item.host, item.port) for item in catalog.sources}
        return sorted(
            (
                (stream.signature, endpoints[stream.source_id])
                for stream in catalog.streams(selected_only=True)
            ),
            key=lambda item: item[0][1],
        )
    return sorted(
        (stream.signature for stream in catalog.streams(selected_only=True)),
        key=lambda signature: signature[1],
    )


class SystemCollectionChange(SystemModel):
    expected_revision: int = Field(ge=0)
    expected_collection_revision: int = Field(ge=0)
    stream_ids: list[EntityId] = Field(min_length=1, max_length=4096)
    policy: CollectionPolicy
    pause_affected_monitors: bool = False


class SystemCollectionScope(SystemModel):
    stream_ids: list[EntityId] = Field(default_factory=list, max_length=4096)


class SystemCollectionPreview(SystemModel):
    revision: int
    collection_revision: int
    selected_readings: int
    sampled_rows_per_day_ceiling: int
    original_rate_readings: int
    affected_monitors: list[dict] = Field(default_factory=list)
