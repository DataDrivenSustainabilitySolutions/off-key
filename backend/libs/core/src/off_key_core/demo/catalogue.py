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


class FeedSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    weather_station: int = Field(default=1003, gt=0, lt=1_000_000)
    traffic_station: int = Field(default=23438, gt=0, lt=1_000_000)
    hamburg_detectors: list[Annotated[int, Field(gt=0)]] = Field(
        default_factory=lambda: [13, 30], min_length=1, max_length=3
    )

    @field_validator("hamburg_detectors")
    @classmethod
    def distinct_detectors(cls, values: list[int]) -> list[int]:
        if len(values) != len(set(values)):
            raise ValueError("Choose distinct Hamburg detectors")
        return values


# Digitraffic road sensor ids by normalized field. Cadence varies by station.
WEATHER_SENSORS = {
    "air_temperature": 1,
    "road_temperature": 3,
    "wind_speed": 16,
    "humidity": 21,
}
TRAFFIC_SENSORS = {
    "volume_1": 5116,
    "volume_2": 5119,
    "speed_1": 5122,
    "speed_2": 5125,
}
MOSQUITTO_ENTITY = "test-mosquitto-org"
MOSQUITTO_SENSORS = {
    "clients": "$SYS/broker/clients/connected",
    "messages_received": "$SYS/broker/load/messages/received/1min",
    "messages_sent": "$SYS/broker/load/messages/sent/1min",
    "bytes_received": "$SYS/broker/load/bytes/received/1min",
}

# (field in normalized message, visible label, unit)
FIELDS = {
    "weather": [
        ("air_temperature", "Air temperature", "°C"),
        ("road_temperature", "Road surface temperature", "°C"),
        ("wind_speed", "Mean wind speed", "m/s"),
        ("humidity", "Relative humidity", "%"),
    ],
    "traffic": [
        ("volume_1", "Vehicles per hour, direction 1", "1/h"),
        ("volume_2", "Vehicles per hour, direction 2", "1/h"),
        ("speed_1", "Average speed, direction 1", "km/h"),
        ("speed_2", "Average speed, direction 2", "km/h"),
    ],
    "hamburg": [("occupancy", "Occupancy", "%")],
    "mosquitto": [
        ("clients", "Connected clients", "clients"),
        ("messages_received", "Messages received, 1-minute average", "messages/min"),
        ("messages_sent", "Messages sent, 1-minute average", "messages/min"),
        ("bytes_received", "Bytes received, 1-minute average", "B/min"),
    ],
}


def entities(selection: FeedSelection) -> dict[str, list[str]]:
    return {
        "weather": [str(selection.weather_station)],
        "traffic": [str(selection.traffic_station)],
        "hamburg": [str(value) for value in selection.hamburg_detectors],
        "mosquitto": [MOSQUITTO_ENTITY],
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
