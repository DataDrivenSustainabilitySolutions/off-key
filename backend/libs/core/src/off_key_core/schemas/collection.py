"""The AmbiBox catalog and the collection policy shared by API and ingestion."""

import re
from dataclasses import dataclass
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_STREAMS = 4096
FORWARD_PORT_START = 20000
FORWARD_PORT_END = 20999


class CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CollectionPolicy(CatalogModel):
    mode: Literal["off", "original", "sample"] = "off"
    interval_seconds: int = Field(default=10, ge=1, le=3600)

    @property
    def cadence(self) -> int | None:
        return self.interval_seconds if self.mode == "sample" else None


class SensorDefinition(CatalogModel):
    key: str = Field(min_length=1, max_length=160, pattern=r"^[\w-]+(?:/[\w-]+)*$")
    label: str = Field(min_length=1, max_length=120)
    category: str = Field(default="Other", min_length=1, max_length=60)
    value_type: Literal["number", "boolean", "text", "identifier"] = "number"
    unit: str | None = Field(default=None, max_length=32)
    upstream_topic: str = Field(min_length=1, max_length=512)
    policy: CollectionPolicy | None = None

    @field_validator("upstream_topic")
    @classmethod
    def concrete_topic(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*", value):
            raise ValueError("Use a concrete AmbiBox topic without wildcards")
        return value


class CatalogCharger(CatalogModel):
    id: UUID = Field(default_factory=uuid4)
    local_id: str = Field(default="0", min_length=1, max_length=80, pattern=r"^[\w-]+$")
    label: str = Field(min_length=1, max_length=120)
    # New chargers stay paused even when the fleet default is enabled.
    policy: CollectionPolicy | None = Field(default_factory=CollectionPolicy)
    sensors: list[SensorDefinition] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def validate_sensors(self) -> Self:
        keys = [sensor.key for sensor in self.sensors]
        topics = [sensor.upstream_topic for sensor in self.sensors]
        if len(keys) != len(set(keys)) or len(topics) != len(set(topics)):
            raise ValueError("Sensor keys and topics must be unique within a charger")
        prefix = f"device/evCharger/{self.local_id}/"
        if any(not topic.startswith(prefix) for topic in topics):
            raise ValueError(f"Charger sensor topics must start with {prefix}")
        return self


class CatalogSource(CatalogModel):
    id: UUID = Field(default_factory=uuid4)
    label: str = Field(min_length=1, max_length=120)
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=1883, ge=1, le=65535)
    verified: bool = False
    forward_port: int | None = Field(
        default=None, ge=FORWARD_PORT_START, le=FORWARD_PORT_END
    )
    chargers: list[CatalogCharger] = Field(default_factory=list, max_length=16)

    @field_validator("host")
    @classmethod
    def hostname(cls, value: str) -> str:
        value = value.lower().rstrip(".")
        label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
        if not re.fullmatch(rf"{label}(?:\.{label})*", value):
            raise ValueError("Use a broker hostname, without a URL or port")
        return value

    @model_validator(mode="after")
    def unique_local_ids(self) -> Self:
        ids = [charger.local_id for charger in self.chargers]
        if len(ids) != len(set(ids)):
            raise ValueError("Local charger IDs must be unique within a broker")
        return self


@dataclass(frozen=True)
class CollectionStream:
    source_id: str
    charger_id: str
    sensor: SensorDefinition
    policy: CollectionPolicy

    @property
    def ingress_topic(self) -> str:
        return f"ingress/ambibox/{self.source_id}/{self.sensor.upstream_topic}"

    @property
    def accepted_topic(self) -> str:
        return f"device/evCharger/{self.charger_id}/{self.sensor.key}"

    @property
    def signature(self) -> tuple:
        return (
            self.ingress_topic,
            self.accepted_topic,
            self.sensor.value_type,
            self.policy.mode,
            self.policy.cadence,
        )


class AmbiboxCatalog(CatalogModel):
    schema_version: Literal[1] = 1
    provider: Literal["ambibox"] = "ambibox"
    default_policy: CollectionPolicy = Field(
        default_factory=lambda: CollectionPolicy(mode="sample")
    )
    sources: list[CatalogSource] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def unique_entities(self) -> Self:
        source_ids = [source.id for source in self.sources]
        endpoints = [(source.host, source.port) for source in self.sources]
        chargers = [charger for source in self.sources for charger in source.chargers]
        charger_ids = [charger.id for charger in chargers]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Source IDs must be unique")
        if len(endpoints) != len(set(endpoints)):
            raise ValueError("Each broker endpoint must appear only once")
        if len(charger_ids) != len(set(charger_ids)):
            raise ValueError("Application charger IDs must be unique across brokers")
        if sum(len(charger.sensors) for charger in chargers) > MAX_STREAMS:
            raise ValueError(f"A catalog may contain at most {MAX_STREAMS} sensors")
        return self

    def streams(self, *, selected_only: bool = False) -> list[CollectionStream]:
        result = []
        for source in self.sources:
            for charger in source.chargers:
                for sensor in charger.sensors:
                    policy = sensor.policy or charger.policy or self.default_policy
                    if selected_only and policy.mode == "off":
                        continue
                    result.append(
                        CollectionStream(
                            str(source.id), str(charger.id), sensor, policy
                        )
                    )
        return result


def assign_forward_ports(
    catalog: AmbiboxCatalog, current: AmbiboxCatalog
) -> AmbiboxCatalog:
    """Keep existing route ports stable and allocate unused ports for new sources."""
    previous = {source.id: source.forward_port for source in current.sources}
    reserved = {
        previous[source.id]
        for source in catalog.sources
        if previous.get(source.id) is not None
    }
    free_ports = (
        port
        for port in range(FORWARD_PORT_START, FORWARD_PORT_END + 1)
        if port not in reserved
    )
    sources = [
        source.model_copy(
            update={"forward_port": previous.get(source.id) or next(free_ports)}
        )
        for source in catalog.sources
    ]
    return catalog.model_copy(update={"sources": sources})


class CatalogChange(CatalogModel):
    expected_revision: int = Field(ge=0)
    catalog: AmbiboxCatalog
    pause_affected_monitors: bool = False


class CatalogSnapshot(CatalogModel):
    revision: int
    catalog: AmbiboxCatalog
    ingress: dict = Field(default_factory=dict)
    collection: dict = Field(default_factory=dict)
    updated_at: str | None = None
    updated_by: str | None = None


class CatalogPreview(CatalogModel):
    revision: int
    catalog: AmbiboxCatalog
    chargers: int
    selected_sensors: int
    sampled_rows_per_day_ceiling: int
    original_rate_sensors: int
    affected_monitors: list[dict] = Field(default_factory=list)
