"""The demo catalogue builder names concrete Digitraffic topics in a valid document."""

import importlib.util
from pathlib import Path

from off_key_core.schemas.system import SystemDocument

ROOT = Path(__file__).parents[3]
spec = importlib.util.spec_from_file_location(
    "digitraffic_catalogue", ROOT / "dev/demo/digitraffic_catalogue.py"
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

HELSINKI = builder.CITIES["helsinki"]


def station(station_id, name, lon, lat, status="GATHERING"):
    return {
        "geometry": {"coordinates": [lon, lat, 0]},
        "properties": {"id": station_id, "name": name, "collectionStatus": status},
    }


STATIONS = {
    "features": [
        station(1, "far", 27.0, 64.0),
        station(2, "near", 24.95, 60.18),
        station(3, "removed", 24.94, 60.17, status="REMOVED_TEMPORARILY"),
    ]
}
WEATHER = {
    "sensorValues": [
        {"id": 1, "name": "ILMA", "unit": "°C"},
        {"id": 21, "name": "ILMAN_KOSTEUS", "unit": "%"},
        {"id": 99, "name": "SADE", "unit": ""},
    ]
}
TRAFFIC = {"sensorValues": [{"id": 5116, "name": "OHITUKSET_5MIN_LIUKUVA_SUUNTA1"}]}
VESSELS = [{"mmsi": 230987000, "name": "MEGASTAR "}, {"mmsi": 1, "name": "OTHER"}]


def document():
    nearest = builder.nearest_stations(STATIONS, HELSINKI, 1)
    weather = builder.station_entities(
        "weather-station",
        "weather-v2",
        "Road weather",
        nearest,
        lambda _: WEATHER,
        builder.WEATHER_SENSORS,
    )
    traffic = builder.station_entities(
        "traffic-station",
        "tms-v2",
        "Traffic",
        nearest,
        lambda _: TRAFFIC,
        builder.TRAFFIC_SENSORS,
    )
    vessel = builder.vessel_entities(VESSELS, "megastar", "location")
    return builder.build("helsinki", weather, traffic, vessel)


def test_the_catalogue_is_a_valid_system_document():
    saved = SystemDocument.model_validate(document())
    assert [c.host for c in saved.connections] == [builder.ROAD, builder.MARINE]
    assert all(c.transport == "websocket" and c.tls for c in saved.connections)
    assert saved.default_policy.mode == "off"
    assert all(stream.policy is None for stream in saved.streams)


def test_the_nearest_collecting_station_supplies_known_sensors():
    topics = {(s["topic"], s["payload_pointer"]) for s in document()["streams"]}
    assert topics == {
        ("weather-v2/2/1", "/value"),
        ("weather-v2/2/21", "/value"),
        ("tms-v2/2/5116", "/value"),
        ("vessels-v2/230987000/location", "/sog"),
        ("vessels-v2/230987000/location", "/cog"),
    }


def test_a_missing_vessel_leaves_only_the_road_feeds():
    assert builder.vessel_entities(VESSELS, "Nobody", "location") == ([], [])


def test_only_numeric_digitraffic_payloads_count_as_received():
    assert builder._numeric(b'{"value": 3.4, "time": 1}')
    assert builder._numeric(b'{"sog": 0, "cog": 12}')
    assert not builder._numeric(b'{"updated": 1}')
    assert not builder._numeric(b"not json")
