"""Pure source decoding; untrusted feeds never select destinations or credentials."""

import json
import math
from datetime import datetime

from off_key_core.demo.catalogue import FeedSelection, topic

MAX_PAYLOAD = 65_536


def timestamp(value) -> float:
    if isinstance(value, str):
        # SensorThings can express an observation as a start/end interval.
        value = datetime.fromisoformat(value.split("/")[-1].replace("Z", "+00:00"))
        if value.tzinfo is None:
            raise ValueError("Source time needs a timezone")
        return value.timestamp()
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Source time must be finite")
    return value / 1000 if value > 100_000_000_000 else float(value)


def _hsl(mqtt_topic: str, data: dict, selection: FeedSelection):
    data = data["VP"]
    entity = f"{int(data['oper']):04d}/{int(data['veh']):05d}"
    if entity != selection.hsl_vehicle:
        return None
    return (
        entity,
        data["tst"],
        {
            name: data.get(key)
            for name, key in {
                "speed": "spd",
                "acceleration": "acc",
                "delay": "dl",
                "doors": "drst",
            }.items()
        },
    )


def _hamburg(mqtt_topic: str, data: dict, selection: FeedSelection):
    entity = mqtt_topic.split("Datastreams(")[1].split(")")[0]
    if entity not in {str(value) for value in selection.hamburg_detectors}:
        return None
    return entity, data["phenomenonTime"], {"occupancy": data.get("result")}


def _marine(mqtt_topic: str, data: dict, selection: FeedSelection):
    entity = mqtt_topic.split("/")[1]
    if entity != selection.marine_mmsi:
        return None
    # AIS uses special numeric values for unavailable measurements.
    fields = {
        name: data.get(key)
        for name, key in {
            "speed": "sog",
            "course": "cog",
            "heading": "heading",
        }.items()
    }
    for field, sentinel in {"speed": 102.3, "course": 360, "heading": 511}.items():
        if fields[field] == sentinel:
            fields[field] = None
    return entity, data["time"], fields


def _rail(mqtt_topic: str, data: dict, selection: FeedSelection):
    entity = str(data["trainNumber"])
    if entity != selection.rail_train:
        return None
    return entity, data["timestamp"], {"speed": data.get("speed")}


def _solar(mqtt_topic: str, data: dict, selection: FeedSelection):
    entity = data["Inverter_ID"]
    if entity != selection.solar_inverter:
        return None
    return (
        entity,
        data["ts"],
        {
            name: data.get(key)
            for name, key in {
                "power": "Output_AC_Power_kW",
                "voltage": "Input_DC_Voltage",
                "temperature": "Temperature_Module",
                "efficiency": "Efficiency_%",
            }.items()
        },
    )


_DECODERS = {
    "hsl": _hsl,
    "hamburg": _hamburg,
    "marine": _marine,
    "rail": _rail,
    "solar": _solar,
}


def decode(source: str, mqtt_topic: str, data: dict, selection: FeedSelection):
    return _DECODERS[source](mqtt_topic, data, selection)


class Normalizer:
    """Bounded state per configured reading; reject duplicates and stale replay."""

    def __init__(self, selection: FeedSelection):
        from off_key_core.demo.catalogue import catalogue

        self.selection = selection
        self.allowed = {reading.topic for reading in catalogue(selection).streams}
        self.latest: dict[str, float] = {}

    def messages(
        self,
        source: str,
        mqtt_topic: str,
        payload: bytes,
        *,
        received_at: float,
        retained: bool = False,
    ) -> list[tuple[str, str]]:
        if retained or len(payload) > MAX_PAYLOAD:
            return []
        try:
            data = json.loads(payload)
            if not isinstance(data, dict):
                return []
            decoded = decode(source, mqtt_topic, data, self.selection)
            if decoded is None:
                return []
            entity, source_time, fields = decoded
            observed_at = timestamp(source_time)
            if not received_at - 120 <= observed_at <= received_at + 10:
                return []
        except (
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            OverflowError,
            RecursionError,
        ):
            return []
        result = []
        for field, raw in fields.items():
            destination = topic(source, entity, field)
            if destination not in self.allowed or observed_at <= self.latest.get(
                destination, 0
            ):
                continue
            try:
                value = float(raw)
            except (ValueError, TypeError, OverflowError):
                continue
            if not math.isfinite(value):
                continue
            self.latest[destination] = observed_at
            result.append(
                (
                    destination,
                    json.dumps(
                        {
                            "value": value,
                            "source": source,
                            "entity": entity,
                            "observed_at": observed_at,
                            "received_at": received_at,
                            "simulated": source == "solar",
                        },
                        allow_nan=False,
                    ),
                )
            )
        return result
