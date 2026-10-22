"""Domain-neutral collection bindings and the explicit opt-in contract."""

import hashlib
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, model_validator

from .collection_policy import CollectionPolicy
from .collection_rules import CollectionRule
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
    rules_version: Literal[1] = 1
    rules: list[CollectionRule] = Field(default_factory=list, max_length=4096)
    registration_clock: int = Field(default=0, ge=0)
    registered_at: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def read_legacy_policies(cls, value):
        if (
            isinstance(value, dict)
            and "rules_version" not in value
            and "document" in value
        ):
            from off_key_core.utils.collection_rules import legacy_rules

            value = dict(value)
            document = SystemDocument.model_validate(value["document"])
            value["rules"] = legacy_rules(document)
            value["registered_at"] = {stream.id: 0 for stream in document.streams}
        return value

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
        # Storage identities are independent of catalogue and upstream topic IDs.
        return self.binding.entity_id

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
    previous: dict[str, ReadingBinding] | None = None,
) -> dict[str, ReadingBinding]:
    """Keep saved bindings by identity; new readings receive deterministic keys."""
    result = {}
    for stream in document.streams:
        existing = (previous or {}).get(stream.id)
        if existing and existing.device_id == stream.device_id:
            result[stream.id] = existing
            continue
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
    changed_readings: int = 0
    starting_readings: int = 0
    stopping_readings: int = 0
    rate_changed_readings: int = 0
    bindings: dict[str, dict] = Field(default_factory=dict)
    rules: list[CollectionRule] = Field(default_factory=list)
