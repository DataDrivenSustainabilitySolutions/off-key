"""Portable, domain-neutral saved structure; this document does not start ingestion."""

import ipaddress
import re
from typing import Annotated, Literal, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .collection_policy import CollectionPolicy

EntityId = Annotated[
    str, Field(min_length=1, max_length=280, pattern=r"^[A-Za-z0-9_:./-]+$")
]


def _has_control(value: str, *, forbid_space: bool = False) -> bool:
    """C0 controls and DEL; paths also reject the space character."""
    floor = 33 if forbid_space else 32
    return any(ord(character) < floor or ord(character) == 127 for character in value)


class SystemModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NamedEntity(SystemModel):
    id: EntityId = Field(default_factory=lambda: str(uuid4()))
    label: str = Field(min_length=1, max_length=120)

    @field_validator("id")
    @classmethod
    def storage_safe_id(cls, value: str) -> str:
        if value in {"__proto__", "constructor", "prototype"}:
            raise ValueError("This stable ID is reserved for configuration storage")
        return value

    @field_validator("label")
    @classmethod
    def readable_label(cls, value: str) -> str:
        value = value.strip()
        if not value or _has_control(value):
            raise ValueError("Use a non-empty name without control characters")
        return value


class SystemConnection(NamedEntity):
    protocol: Literal["mqtt"] = "mqtt"
    transport: Literal["tcp", "websocket"] = "tcp"
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=1883, ge=1, le=65535)
    tls: bool = False
    websocket_path: str | None = Field(default=None, max_length=512)
    credential_ref: str | None = Field(
        default=None, min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_:./-]+$"
    )

    @field_validator("credential_ref")
    @classmethod
    def storage_safe_credential_reference(cls, value: str | None) -> str | None:
        return NamedEntity.storage_safe_id(value) if value is not None else None

    @field_validator("host")
    @classmethod
    def broker_host(cls, value: str) -> str:
        value = value.lower().rstrip(".")
        try:
            return ipaddress.ip_address(value).compressed
        except ValueError:
            label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
            if not re.fullmatch(rf"{label}(?:\.{label})*", value):
                raise ValueError(
                    "Use a broker hostname or IP address, without a URL or port"
                ) from None
            return value

    @model_validator(mode="after")
    def transport_fields(self) -> Self:
        if self.websocket_path is not None and (
            self.transport != "websocket"
            or not self.websocket_path.startswith("/")
            or _has_control(self.websocket_path, forbid_space=True)
            or "#" in self.websocket_path
        ):
            raise ValueError(
                "WebSocket paths must start with / and belong to a WebSocket connection"
            )
        return self


class SystemDevice(NamedEntity):
    connection_id: EntityId | None = None
    parent_id: EntityId | None = None
    kind: str = Field(default="device", min_length=1, max_length=60)

    @field_validator("kind")
    @classmethod
    def bounded_kind(cls, value: str) -> str:
        if not value.strip() or _has_control(value):
            raise ValueError("Use a device kind without control characters")
        return value.strip()


class SystemStream(NamedEntity):
    connection_id: EntityId
    device_id: EntityId | None = None
    topic: str = Field(min_length=1, max_length=512)
    payload_pointer: str | None = Field(default=None, max_length=512)
    value_type: Literal["number", "boolean", "text", "identifier"] = "number"
    unit: str | None = Field(default=None, max_length=32)
    category: str = Field(default="Other", min_length=1, max_length=60)
    policy: CollectionPolicy | None = None

    @field_validator("topic")
    @classmethod
    def concrete_topic(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 512 or any(
            character in value for character in ("\x00", "+", "#")
        ):
            raise ValueError(
                "Use a concrete MQTT topic of at most 512 UTF-8 bytes, "
                "without wildcards or NUL"
            )
        if _has_control(value):
            raise ValueError("MQTT topics must not contain control characters")
        return value

    @field_validator("payload_pointer")
    @classmethod
    def json_pointer(cls, value: str | None) -> str | None:
        if value is not None and (
            not re.fullmatch(r"(?:/(?:[^~/]|~[01])*)*", value) or _has_control(value)
        ):
            raise ValueError(
                "Use an RFC 6901 JSON Pointer, such as /readings/temperature"
            )
        return value

    @field_validator("unit", "category")
    @classmethod
    def readable_metadata(cls, value: str | None) -> str | None:
        if value is not None and _has_control(value):
            raise ValueError("Metadata must not contain control characters")
        return value


class SystemGroup(NamedEntity):
    color: str = Field(default="#7d9b8b", pattern=r"^#[0-9a-fA-F]{6}$")
    member_ids: list[EntityId] = Field(default_factory=list, max_length=8192)


class SystemDocument(SystemModel):
    schema_version: Literal[1] = 1
    format: Literal["aberration-system"] = "aberration-system"
    label: str = Field(default="My system", min_length=1, max_length=120)
    default_policy: CollectionPolicy = Field(default_factory=CollectionPolicy)
    connections: list[SystemConnection] = Field(default_factory=list, max_length=128)
    devices: list[SystemDevice] = Field(default_factory=list, max_length=2048)
    streams: list[SystemStream] = Field(default_factory=list, max_length=4096)
    groups: list[SystemGroup] = Field(default_factory=list, max_length=128)

    @field_validator("label")
    @classmethod
    def system_name(cls, value: str) -> str:
        return NamedEntity.readable_label(value)

    @model_validator(mode="after")
    def valid_structure(self) -> Self:
        entities = [*self.connections, *self.devices, *self.streams, *self.groups]
        ids = [entity.id for entity in entities]
        if len(ids) != len(set(ids)):
            raise ValueError("Stable IDs must be unique across the system")
        connections = {connection.id for connection in self.connections}
        devices = {device.id: device for device in self.devices}
        members = {
            entity.id for entity in [*self.connections, *self.devices, *self.streams]
        }
        for device in self.devices:
            if (
                device.connection_id is not None
                and device.connection_id not in connections
            ):
                raise ValueError("Device connection does not exist")
            if device.parent_id is not None and device.parent_id not in devices:
                raise ValueError("Parent device does not exist")
        self._validate_device_parents(devices)
        self._validate_stream_references(connections, set(devices))
        if any(f"group:{group.id}" in members for group in self.groups):
            raise ValueError("An entity ID conflicts with a collapsed group identity")
        self._validate_group_members(members)
        if len(self.model_dump_json().encode("utf-8")) > 1_048_576:
            raise ValueError(
                "A system document may contain at most 1 MiB of configuration"
            )
        return self

    def _validate_group_members(self, members: set[str]) -> None:
        assigned = set()
        for group in self.groups:
            proposed = set(group.member_ids)
            if len(group.member_ids) != len(proposed) or not proposed <= members:
                raise ValueError(
                    "Group members must be unique existing connections, "
                    "devices, or streams"
                )
            if assigned.intersection(proposed):
                raise ValueError("Each entity may belong to at most one spatial group")
            assigned.update(proposed)

    def _validate_stream_references(
        self, connections: set[str], devices: set[str]
    ) -> None:
        for stream in self.streams:
            if stream.connection_id not in connections:
                raise ValueError("Stream connection does not exist")
            if stream.device_id is not None and stream.device_id not in devices:
                raise ValueError("Stream device does not exist")

    @staticmethod
    def _validate_device_parents(devices: dict[str, SystemDevice]) -> None:
        complete = set()
        for device_id in devices:
            path = set()
            current = device_id
            while current is not None and current not in complete:
                if current in path:
                    raise ValueError("Device parents must not form a cycle")
                path.add(current)
                current = devices[current].parent_id
            complete.update(path)


class SystemChange(SystemModel):
    expected_revision: int = Field(ge=0)
    document: SystemDocument
    pause_affected_monitors: bool = False


class SystemRuntime(SystemModel):
    mode: Literal["configured_only", "collection"] = "configured_only"
    message: str = (
        "Saved structure only. Generic connections are not started "
        "by saving this configuration."
    )
    collection_revision: int = 0
    collection: dict = Field(default_factory=dict)
    ingress: dict = Field(default_factory=dict)
    bindings: dict[str, dict] = Field(default_factory=dict)
    latest_readings: dict[str, dict] = Field(default_factory=dict)
    collection_rules: list[dict] = Field(default_factory=list)


class SystemSnapshot(SystemModel):
    revision: int
    document: SystemDocument
    storage_origin: Literal["saved", "empty"]
    runtime: SystemRuntime = Field(default_factory=SystemRuntime)
    updated_at: str | None = None
    updated_by: str | None = None
