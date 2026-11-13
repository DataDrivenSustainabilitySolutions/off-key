"""Pure source decoding; untrusted feeds never select destinations or credentials."""

import json
import math
from datetime import datetime

from off_key_core.demo.catalogue import (
    MOSQUITTO_ENTITY,
    MOSQUITTO_SENSORS,
    TRAFFIC_SENSORS,
    WEATHER_SENSORS,
    FeedSelection,
    topic,
)

MAX_PAYLOAD = 65_536
# Seconds an observation may be old on arrival. Road stations measure, then
# publish about a minute later, so they get a wider window than the live feeds.
MAX_AGE = {"weather": 600, "traffic": 600}
DEFAULT_MAX_AGE = 120


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


def _road(sensors: dict[str, int], station: int, mqtt_topic: str, data: dict):
    # <network>-v2/<station>/<sensor>; the status topic carries no measurement.
    _network, entity, sensor = mqtt_topic.split("/")
    if entity != str(station):
        return None
    field = {value: key for key, value in sensors.items()}.get(int(sensor))
    if field is None:
        return None
    return entity, data["time"], {field: data.get("value")}


def _weather(mqtt_topic: str, data: dict, selection: FeedSelection):
    return _road(WEATHER_SENSORS, selection.weather_station, mqtt_topic, data)


def _traffic(mqtt_topic: str, data: dict, selection: FeedSelection):
    return _road(TRAFFIC_SENSORS, selection.traffic_station, mqtt_topic, data)


def _hamburg(mqtt_topic: str, data: dict, selection: FeedSelection):
    entity = mqtt_topic.split("Datastreams(")[1].split(")")[0]
    if entity not in {str(value) for value in selection.hamburg_detectors}:
        return None
    return entity, data["phenomenonTime"], {"occupancy": data.get("result")}


def _mosquitto(mqtt_topic: str, data, _selection: FeedSelection):
    field = {value: key for key, value in MOSQUITTO_SENSORS.items()}.get(mqtt_topic)
    if field is None or type(data) not in (int, float) or data < 0:
        return None
    # $SYS values have no observation timestamp. Never invent one for the source.
    return MOSQUITTO_ENTITY, None, {field: data}


_DECODERS = {
    "weather": _weather,
    "traffic": _traffic,
    "hamburg": _hamburg,
    "mosquitto": _mosquitto,
}


def decode(source: str, mqtt_topic: str, data, selection: FeedSelection):
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
            if source != "mosquitto" and not isinstance(data, dict):
                return []
            decoded = decode(source, mqtt_topic, data, self.selection)
            if decoded is None:
                return []
            entity, source_time, fields = decoded
            observed_at = None if source == "mosquitto" else timestamp(source_time)
            event_time = received_at if observed_at is None else observed_at
            max_age = MAX_AGE.get(source, DEFAULT_MAX_AGE)
            if not received_at - max_age <= event_time <= received_at + 10:
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
            if destination not in self.allowed or event_time <= self.latest.get(
                destination, 0
            ):
                continue
            try:
                value = float(raw)
            except (ValueError, TypeError, OverflowError):
                continue
            if not math.isfinite(value):
                continue
            self.latest[destination] = event_time
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
                            "simulated": False,
                        },
                        allow_nan=False,
                    ),
                )
            )
        return result
