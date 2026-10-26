"""Build the public demo's source catalogue from Fintraffic Digitraffic open data.

Three low-volume, always-on MQTT feeds from Finland's national traffic agency
(open data, CC BY 4.0, anonymous access):

- Road weather: air and road temperature, humidity and wind at the road weather
  station nearest a city; Digitraffic updates each sensor about once a minute.
- Traffic measurement: hourly vehicle counts and the 5-minute average speed at
  the measurement station nearest the city, about once a minute.
- AIS: speed and course over ground of one named passenger ferry.

The REST API supplies today's station and vessel IDs, so the catalogue names
concrete topics. ``--verify`` subscribes for a short while and keeps only
readings that actually arrived. Write the result to a file and import it under
Sources; recording stays Off until an administrator applies a policy.

    uv run --project backend python dev/demo/digitraffic_catalogue.py \
        --verify --output digitraffic-system.json
"""

import argparse
import gzip
import json
import math
import sys
import time
import urllib.request
import uuid
from pathlib import Path

ROAD = "tie.digitraffic.fi"
MARINE = "meri.digitraffic.fi"
# Digitraffic asks every client to identify itself.
USER = "aberration-demo"
ATTRIBUTION = "Fintraffic Digitraffic, CC BY 4.0"
CITIES = {
    "helsinki": (60.1699, 24.9384),
    "tampere": (61.4978, 23.7610),
    "turku": (60.4518, 22.2666),
    "oulu": (65.0121, 25.4651),
}
# Sensor name, label, fallback unit, category; the station data names the unit.
WEATHER_SENSORS = (
    ("ILMA", "Air temperature", "°C", "Temperature"),
    ("TIE_1", "Road surface temperature", "°C", "Temperature"),
    ("ILMAN_KOSTEUS", "Relative humidity", "%", "Humidity"),
    ("KESKITUULI", "Average wind speed", "m/s", "Wind"),
)
# Sliding 5-minute values change every minute; fixed hourly counts would not.
TRAFFIC_SENSORS = (
    ("OHITUKSET_5MIN_LIUKUVA_SUUNTA1", "Traffic flow, direction 1", "kpl/h", "Traffic"),
    ("OHITUKSET_5MIN_LIUKUVA_SUUNTA2", "Traffic flow, direction 2", "kpl/h", "Traffic"),
    ("KESKINOPEUS_5MIN_LIUKUVA_SUUNTA1", "Average speed, direction 1", "km/h", "Speed"),
    ("KESKINOPEUS_5MIN_LIUKUVA_SUUNTA2", "Average speed, direction 2", "km/h", "Speed"),
)
VESSEL_READINGS = (
    ("/sog", "Speed over ground", "kn", "Speed"),
    ("/cog", "Course over ground", "°", "Course"),
)


def fetch(host: str, path: str):
    request = urllib.request.Request(
        f"https://{host}{path}",
        headers={"Digitraffic-User": USER, "Accept-Encoding": "gzip"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
    return json.loads(body)


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    (lat1, lon1), (lat2, lon2) = (tuple(map(math.radians, p)) for p in (a, b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 12_742 * math.asin(math.sqrt(h))


def nearest_stations(stations: dict, city: tuple[float, float], count: int) -> list:
    """Collecting stations by distance; GeoJSON coordinates are lon, lat."""
    gathering = [
        feature
        for feature in stations.get("features", [])
        if feature.get("properties", {}).get("collectionStatus") == "GATHERING"
        and feature.get("geometry", {}).get("coordinates")
    ]
    return sorted(
        gathering,
        key=lambda feature: distance_km(
            city, tuple(reversed(feature["geometry"]["coordinates"][:2]))
        ),
    )[:count]


def station_readings(data: dict, wanted) -> list[tuple[int, str, str, str]]:
    """Sensor id, label, unit and category for each wanted sensor the station has."""
    by_name = {sensor["name"]: sensor for sensor in data.get("sensorValues", [])}
    return [
        (by_name[name]["id"], label, by_name[name].get("unit") or unit, category)
        for name, label, unit, category in wanted
        if name in by_name
    ]


def connection(host: str, label: str) -> dict:
    return {
        "id": f"broker:{host}",
        "label": label,
        "protocol": "mqtt",
        "transport": "websocket",
        "host": host,
        "port": 443,
        "tls": True,
        "websocket_path": "/mqtt",
        "credential_ref": None,
    }


def entity(kind: str, key: str, label: str, host: str) -> dict:
    return {
        "id": f"entity:digitraffic:{kind}:{key}",
        "label": label,
        "connection_id": f"broker:{host}",
        "parent_id": None,
        "kind": kind,
    }


def reading(device: dict, key: str, topic: str, pointer, label, unit, category):
    return {
        "id": f"reading:{device['id'].removeprefix('entity:')}:{key}",
        "label": label,
        "connection_id": device["connection_id"],
        "device_id": device["id"],
        "topic": topic,
        "payload_pointer": pointer,
        "value_type": "number",
        "unit": unit,
        "category": category,
        "policy": None,
    }


def station_entities(kind, topic_root, label, stations, data_for, wanted):
    devices, streams = [], []
    for station in stations:
        station_id = station["properties"]["id"]
        name = station["properties"].get("name") or str(station_id)
        sensors = station_readings(data_for(station_id), wanted)
        if not sensors:
            continue
        device = entity(kind, str(station_id), f"{label} {name}", ROAD)
        devices.append(device)
        streams += [
            reading(
                device,
                str(sensor_id),
                f"{topic_root}/{station_id}/{sensor_id}",
                "/value",
                sensor_label,
                unit,
                category,
            )
            for sensor_id, sensor_label, unit, category in sensors
        ]
    return devices, streams


def vessel_entities(vessels: list, name: str, topic_leaf: str):
    match = next(
        (
            vessel
            for vessel in vessels
            if (vessel.get("name") or "").strip().upper() == name.upper()
        ),
        None,
    )
    if match is None:
        return [], []
    mmsi = str(match["mmsi"])
    device = entity("vessel", mmsi, f"Ferry {match['name'].strip().title()}", MARINE)
    streams = [
        reading(
            device,
            pointer.strip("/"),
            f"vessels-v2/{mmsi}/{topic_leaf}",
            pointer,
            label,
            unit,
            category,
        )
        for pointer, label, unit, category in VESSEL_READINGS
    ]
    return [device], streams


def build(city: str, weather, traffic, vessel) -> dict:
    devices = [*weather[0], *traffic[0], *vessel[0]]
    streams = [*weather[1], *traffic[1], *vessel[1]]
    hosts = {device["connection_id"].removeprefix("broker:") for device in devices}
    connections = [
        connection(
            host, f"Digitraffic {'road' if host == ROAD else 'marine'} ({ATTRIBUTION})"
        )
        for host in (ROAD, MARINE)
        if host in hosts
    ]
    return {
        "schema_version": 1,
        "format": "aberration-system",
        "label": f"Open data demo: {city.title()}",
        "default_policy": {"mode": "off", "interval_seconds": 60},
        "connections": connections,
        "devices": devices,
        "streams": streams,
        "groups": [],
    }


def listen(host: str, topics: set[str], seconds: float) -> set[str]:
    """Topics on one broker that delivered a numeric value within the time."""
    import paho.mqtt.client as mqtt

    received: set[str] = set()

    def on_connect(client, *_):
        for topic in topics:
            client.subscribe(topic)

    def on_message(_client, _userdata, message):
        if _numeric(message.payload):
            received.add(message.topic)

    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"{USER}-{uuid.uuid4().hex[:8]}",
        transport="websockets",
    )
    client.tls_set()
    client.ws_set_options(path="/mqtt")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(host, 443, 30)
    client.loop_start()
    time.sleep(seconds)
    client.loop_stop()
    client.disconnect()
    return received


def verify(document: dict, seconds: float) -> dict:
    """Keep the readings whose topics delivered a numeric value in time."""
    topics: dict[str, set[str]] = {}
    for stream in document["streams"]:
        host = stream["connection_id"].removeprefix("broker:")
        topics.setdefault(host, set()).add(stream["topic"])
    received = {
        (host, topic)
        for host, wanted in topics.items()
        for topic in listen(host, wanted, seconds)
    }

    def seen(stream):
        return (
            stream["connection_id"].removeprefix("broker:"),
            stream["topic"],
        ) in received

    kept = [stream for stream in document["streams"] if seen(stream)]
    for stream in document["streams"]:
        if not seen(stream):
            print(f"Silent, left out: {stream['topic']}", file=sys.stderr)
    used = {stream["device_id"] for stream in kept}
    devices = [device for device in document["devices"] if device["id"] in used]
    hosts = {device["connection_id"] for device in devices}
    return document | {
        "devices": devices,
        "streams": kept,
        "connections": [c for c in document["connections"] if c["id"] in hosts],
    }


def _numeric(payload: bytes) -> bool:
    try:
        data = json.loads(payload)
    except ValueError:
        return False
    return isinstance(data, dict) and any(
        isinstance(data.get(key), int | float) for key in ("value", "sog")
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--city", choices=sorted(CITIES), default="helsinki")
    parser.add_argument("--stations", type=int, default=1, help="stations per feed")
    parser.add_argument("--vessel", default="MEGASTAR", help="AIS vessel name")
    parser.add_argument(
        "--vessel-topic", choices=("location", "locations"), default="location"
    )
    parser.add_argument(
        "--verify",
        type=float,
        nargs="?",
        const=150.0,
        default=None,
        metavar="SECONDS",
        help="keep only readings seen within SECONDS",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    city = CITIES[args.city]

    weather = station_entities(
        "weather-station",
        "weather-v2",
        "Road weather",
        nearest_stations(fetch(ROAD, "/api/weather/v1/stations"), city, args.stations),
        lambda station: fetch(ROAD, f"/api/weather/v1/stations/{station}/data"),
        WEATHER_SENSORS,
    )
    traffic = station_entities(
        "traffic-station",
        "tms-v2",
        "Traffic",
        nearest_stations(fetch(ROAD, "/api/tms/v1/stations"), city, args.stations),
        lambda station: fetch(ROAD, f"/api/tms/v1/stations/{station}/data"),
        TRAFFIC_SENSORS,
    )
    vessel = vessel_entities(
        fetch(MARINE, "/api/ais/v1/vessels"), args.vessel, args.vessel_topic
    )
    if not vessel[0]:
        print(
            f"No AIS vessel named {args.vessel}; the ferry feed is left out.",
            file=sys.stderr,
        )
    document = build(args.city, weather, traffic, vessel)
    if args.verify is not None:
        document = verify(document, args.verify)
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    print(
        f"{len(document['devices'])} entities, {len(document['streams'])} readings.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
