"""Bounded source selections and a normal, editable application catalogue.

The relay stabilizes moving MQTT topics and separates multiplexed assets. Entity
ids remain in every topic and reading id, so changing an asset cannot splice its
history into another asset's readings.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..schemas.collection_policy import CollectionPolicy
from ..schemas.system import (
    SystemConnection,
    SystemDevice,
    SystemDocument,
    SystemStream,
)
from .sources import SOURCES

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,60}$")]


class FeedSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    hsl_vehicle: str = Field(default="0040/00639", pattern=r"^\d{4}/\d{5}$")
    hamburg_detectors: list[Annotated[int, Field(gt=0)]] = Field(
        default_factory=lambda: [13, 30], min_length=1, max_length=3
    )
    marine_mmsi: str = Field(default="372777000", pattern=r"^\d{9}$")
    rail_train: str = Field(default="38", pattern=r"^\d{1,6}$")
    solar_inverter: Identifier = "INV_001_001"

    @field_validator("hamburg_detectors")
    @classmethod
    def distinct_detectors(cls, values: list[int]) -> list[int]:
        if len(values) != len(set(values)):
            raise ValueError("Choose distinct Hamburg detectors")
        return values


# (field in normalized message, visible label, unit)
FIELDS = {
    "hsl": [
        ("speed", "Speed", "m/s"),
        ("acceleration", "Acceleration", "m/s²"),
        ("delay", "Schedule offset", "s"),
        ("doors", "Doors open", None),
    ],
    "hamburg": [("occupancy", "Occupancy", "%")],
    "marine": [
        ("speed", "Speed over ground", "kn"),
        ("course", "Course", "°"),
        ("heading", "Heading", "°"),
    ],
    "rail": [("speed", "Speed", "km/h")],
    "solar": [
        ("power", "AC power", "kW"),
        ("voltage", "DC voltage", "V"),
        ("temperature", "Module temperature", "°C"),
        ("efficiency", "Efficiency", "%"),
    ],
}


def entities(selection: FeedSelection) -> dict[str, list[str]]:
    return {
        "hsl": [selection.hsl_vehicle],
        "hamburg": [str(value) for value in selection.hamburg_detectors],
        "marine": [selection.marine_mmsi],
        "rail": [selection.rail_train],
        "solar": [selection.solar_inverter],
    }


def topic(source: str, entity: str, field: str) -> str:
    return f"demo/{source}/{entity}/{field}"


def catalogue(selection: FeedSelection, *, host: str = "demo-broker") -> SystemDocument:
    document = SystemDocument(
        label="Public MQTT sources",
        default_policy=CollectionPolicy(mode="sample", interval_seconds=5),
    )
    for source in SOURCES:
        broker_id = f"demo-{source.id}"
        document.connections.append(
            SystemConnection(id=broker_id, label=source.name, host=host)
        )
        for entity in entities(selection)[source.id]:
            device_id = f"{broker_id}:{entity.replace('/', ':')}"
            document.devices.append(
                SystemDevice(
                    id=device_id,
                    label=f"{source.name} · {entity}",
                    connection_id=broker_id,
                )
            )
            for field, label, unit in FIELDS[source.id]:
                document.streams.append(
                    SystemStream(
                        id=f"{device_id}:{field}",
                        label=label,
                        connection_id=broker_id,
                        device_id=device_id,
                        topic=topic(source.id, entity, field),
                        payload_pointer="/value",
                        unit=unit,
                        category="Simulated" if source.simulated else source.name,
                    )
                )
    return SystemDocument.model_validate(document.model_dump())
