"""Reproducible synthetic catalog and real MQTT publisher for the spatial draft."""

import argparse
import json
import math
import signal
import threading
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Entity:
    name: str
    label: str
    kind: str
    reading: str
    unit: str
    baseline: float
    amplitude: float


@dataclass(frozen=True)
class Broker:
    name: str
    label: str
    entities: tuple[Entity, ...]

    @property
    def host(self) -> str:
        return f"fixture-broker-{self.name}"

    @property
    def id(self) -> str:
        return f"fixture:{self.name}"


@dataclass(frozen=True)
class Channel:
    path: str
    label: str
    category: str
    unit: str
    baseline: float
    amplitude: float


BROKERS = (
    Broker(
        "campus",
        "Campus · shared broker",
        tuple(
            Entity(
                f"room-{index:02}",
                f"Room {index:02}",
                "room",
                "Temperature",
                "°C",
                21 + index * 0.15,
                1.4,
            )
            for index in range(1, 13)
        ),
    ),
    Broker(
        "production",
        "Production · shared broker",
        tuple(
            Entity(
                f"station-{index:02}",
                f"Station {index:02}",
                "machine",
                "Vibration",
                "mm/s",
                1 + index * 0.12,
                0.6,
            )
            for index in range(1, 13)
        ),
    ),
    Broker(
        "greenhouse",
        "Greenhouse · shared broker",
        tuple(
            Entity(
                f"bed-{index:02}",
                f"Growing bed {index:02}",
                "growing-bed",
                "Soil moisture",
                "%",
                45 + index * 0.7,
                5,
            )
            for index in range(1, 13)
        ),
    ),
    Broker(
        "meter",
        "Power meter · dedicated broker",
        (Entity("main-meter", "Main power meter", "meter", "Power", "kW", 18, 7),),
    ),
    Broker(
        "weather",
        "Weather station · dedicated broker",
        (
            Entity(
                "roof-station",
                "Roof weather station",
                "weather-station",
                "Wind speed",
                "m/s",
                4.5,
                3,
            ),
        ),
    ),
    Broker(
        "pump",
        "Water pump · dedicated broker",
        (Entity("water-pump", "Water pump", "pump", "Pressure", "bar", 3.2, 0.5),),
    ),
)

CADENCES = (0.8, 1.2, 2.0, 3.0, 5.0, 8.0)
DENSE_CADENCES = (4.0, 6.0, 8.0, 12.0, 16.0, 24.0)
TICK_SECONDS = 0.1
MAX_MESSAGES_PER_TICK = 6
HEARTBEAT = Path("/tmp/broker-fixture.ready")


def entity_id(broker: Broker, entity: Entity) -> str:
    return f"{broker.id}:{entity.name}"


def topic(broker: Broker, entity: Entity) -> str:
    return f"demo/{broker.name}/{entity.name}/telemetry"


def dense_channels(broker: Broker, entity: Entity) -> tuple[Channel, ...]:
    """Distinct real topics on two entities exercise dense source catalogs."""
    if broker.name == "production" and entity.name == "station-01":
        return tuple(
            Channel(
                f"{category.lower()}/sensor-{index:02}/{field}",
                f"{label} {index:02}",
                category,
                unit,
                baseline + index * increment,
                amplitude,
            )
            for category, field, label, unit, baseline, increment, amplitude in (
                ("Thermal", "temperature", "Temperature probe", "°C", 32, 0.8, 3),
                (
                    "Mechanical",
                    "vibration",
                    "Vibration channel",
                    "mm/s",
                    0.8,
                    0.05,
                    0.3,
                ),
                ("Electrical", "current", "Motor current", "A", 2, 0.4, 1),
                ("Diagnostics", "latency", "Controller latency", "ms", 8, 0.3, 2),
            )
            for index in range(1, 13)
        )
    if broker.name == "meter" and entity.name == "main-meter":
        return tuple(
            Channel(
                f"circuits/circuit-{circuit:02}/phase-{phase.lower()}/{field}",
                f"Circuit {circuit:02} · {phase} {field}",
                "Electrical",
                unit,
                baseline + circuit * increment,
                amplitude,
            )
            for circuit in range(1, 9)
            for phase in ("L1", "L2", "L3")
            for field, unit, baseline, increment, amplitude in (
                ("voltage", "V", 229, 0.1, 1.5),
                ("current", "A", 6, 0.4, 1.5),
                ("power", "kW", 1.4, 0.1, 0.3),
                ("frequency", "Hz", 50, 0, 0.03),
            )
        )
    return ()


def channel_topic(broker: Broker, entity: Entity, channel: Channel) -> str:
    return f"demo/{broker.name}/{entity.name}/{channel.path}"


def build_document() -> dict:
    """Hard broker/entity/topic structure, without personal spatial groups."""
    connections, devices, streams = [], [], []
    for broker in BROKERS:
        connections.append(
            {
                "id": broker.id,
                "label": broker.label,
                "protocol": "mqtt",
                "host": broker.host,
                "port": 1883,
                "transport": "tcp",
                "tls": False,
            }
        )
        for entity in broker.entities:
            identifier = entity_id(broker, entity)
            devices.append(
                {
                    "id": identifier,
                    "label": entity.label,
                    "kind": entity.kind,
                    "connection_id": broker.id,
                }
            )
            for field, label, value_type in (
                ("value", entity.reading, "number"),
                ("active", "Active", "boolean"),
                ("mode", "Operating mode", "text"),
                ("sample_id", "Sample identifier", "identifier"),
            ):
                stream = {
                    "id": f"{identifier}:{field}",
                    "label": label,
                    "connection_id": broker.id,
                    "device_id": identifier,
                    "topic": topic(broker, entity),
                    "payload_pointer": f"/{field}",
                    "value_type": value_type,
                    "category": "Measurement" if field == "value" else "State",
                }
                if field == "value":
                    stream["unit"] = entity.unit
                streams.append(stream)
            for channel in dense_channels(broker, entity):
                streams.append(
                    {
                        "id": f"{identifier}:channel:{channel.path}",
                        "label": channel.label,
                        "connection_id": broker.id,
                        "device_id": identifier,
                        "topic": channel_topic(broker, entity, channel),
                        "payload_pointer": "/value",
                        "value_type": "number",
                        "unit": channel.unit,
                        "category": channel.category,
                    }
                )
    return {
        "format": "aberration-system",
        "schema_version": 1,
        "label": "Connected places · synthetic MQTT",
        "default_policy": {"mode": "off", "interval_seconds": 10},
        "connections": connections,
        "devices": devices,
        "streams": streams,
        "groups": [],
    }


def build_payload(entity: Entity, index: int, elapsed: float, sequence: int) -> dict:
    """Deterministic smooth readings and independent, slower state transitions."""
    active = int(elapsed // 35 + index) % 5 != 0
    phase = elapsed / (11 + index % 7) + index * 0.67
    return {
        "value": round(entity.baseline + entity.amplitude * math.sin(phase), 3),
        "active": active,
        "mode": "Running" if active else "Standby",
        "sample_id": f"{entity.name}-{sequence:08}",
    }


def build_channel_payload(channel: Channel, index: int, elapsed: float) -> dict:
    phase = elapsed / (13 + index % 11) + index * 0.73
    return {"value": round(channel.baseline + channel.amplitude * math.sin(phase), 3)}


@dataclass
class Publication:
    broker: Broker
    entity: Entity
    index: int
    cadence: float
    due: float
    channel: Channel | None = None
    sequence: int = 0

    @property
    def topic(self) -> str:
        if self.channel is not None:
            return channel_topic(self.broker, self.entity, self.channel)
        return topic(self.broker, self.entity)

    def payload(self, elapsed: float) -> dict:
        if self.channel is not None:
            return build_channel_payload(self.channel, self.index, elapsed)
        return build_payload(self.entity, self.index, elapsed, self.sequence)


def build_publications() -> list[Publication]:
    publications = []
    base_index = dense_index = 0
    for broker in BROKERS:
        for entity in broker.entities:
            cadence = CADENCES[base_index % len(CADENCES)]
            publications.append(
                Publication(broker, entity, base_index, cadence, base_index * 0.05)
            )
            base_index += 1
            for channel in dense_channels(broker, entity):
                cadence = DENSE_CADENCES[dense_index % len(DENSE_CADENCES)]
                publications.append(
                    Publication(
                        broker,
                        entity,
                        dense_index,
                        cadence,
                        cadence * ((dense_index * 0.61803398875) % 1),
                        channel,
                    )
                )
                dense_index += 1
    return publications


class PublishSchedule:
    """One pending value per topic; round-robin fairness and bounded send bursts."""

    def __init__(self, publications: list[Publication]):
        self.publications = publications
        self.cursor = 0

    def next_batch(self, elapsed: float) -> list[Publication]:
        batch = []
        count = len(self.publications)
        for offset in range(count):
            index = (self.cursor + offset) % count
            publication = self.publications[index]
            if publication.due > elapsed:
                continue
            # Calculate the next deadline from now, never replay missed intervals.
            publication.due = elapsed + publication.cadence
            publication.sequence += 1
            batch.append(publication)
            if len(batch) == MAX_MESSAGES_PER_TICK:
                self.cursor = (index + 1) % count
                break
        return batch


def publish() -> None:
    """Six independent brokers, bounded QoS 0 publisher queues, no retention."""
    import paho.mqtt.client as mqtt

    stopped = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopped.set())
    clients = {}
    schedule = PublishSchedule(build_publications())
    for broker in BROKERS:
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"broker-fixture-{broker.name}",
            clean_session=True,
        )
        client.max_queued_messages_set(64)
        client.max_inflight_messages_set(8)
        client.reconnect_delay_set(1, 15)
        client.connect_async(broker.host, 1883, keepalive=30)
        client.loop_start()
        clients[broker.name] = client
    start = time.monotonic()
    try:
        while not stopped.is_set():
            elapsed = time.monotonic() - start
            for publication in schedule.next_batch(elapsed):
                client = clients[publication.broker.name]
                if client.is_connected():
                    client.publish(
                        publication.topic,
                        json.dumps(publication.payload(elapsed), allow_nan=False),
                        qos=0,
                        retain=False,
                    )
            if all(client.is_connected() for client in clients.values()):
                HEARTBEAT.write_text(str(time.time()))
            stopped.wait(TICK_SECONDS)
    finally:
        for client in clients.values():
            client.disconnect()
            client.loop_stop()
        HEARTBEAT.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_mutually_exclusive_group(required=True)
    commands.add_argument("--publish", action="store_true")
    commands.add_argument("--write-catalog", action="store_true")
    commands.add_argument("--check-catalog", action="store_true")
    args = parser.parse_args()
    if args.publish:
        publish()
        return
    path = Path(__file__).with_name("broker-system.json")
    if args.write_catalog:
        path.write_text(
            json.dumps(build_document(), indent=2, ensure_ascii=False) + "\n"
        )
        document = build_document()
        print(
            f"Wrote {path.name}: {len(document['connections'])} brokers, "
            f"{len(document['devices'])} entities, "
            f"{len(document['streams'])} streams, "
            f"{len(build_publications())} distinct MQTT topics."
        )
    elif json.loads(path.read_text()) != build_document():
        parser.exit(1, "Catalog differs; regenerate using --write-catalog.\n")


if __name__ == "__main__":
    main()
