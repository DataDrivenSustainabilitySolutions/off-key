"""Provider-shaped messages must become stable, fresh application readings."""

import json
from datetime import UTC, datetime

import pytest
from off_key_core.demo.catalogue import FeedSelection, catalogue
from off_key_core.demo.sources import public_sources
from off_key_core.schemas.system import SystemDocument
from off_key_mqtt_proxy.demo.normalize import DEFAULT_MAX_AGE, MAX_AGE, Normalizer
from off_key_mqtt_proxy.demo.relay import feeds

NOW = 1_794_475_800.0
ISO = datetime.fromtimestamp(NOW, UTC).isoformat()
SELECTION = FeedSelection()
MESSAGES = [
    (
        "weather",
        "weather-v2/4057/3",
        {"value": -1.4, "time": int(NOW)},
        1,
    ),
    (
        "traffic",
        "tms-v2/23438/5122",
        {"value": 87, "time": int(NOW), "start": int(NOW) - 300, "end": int(NOW)},
        1,
    ),
    (
        "hamburg",
        "v1.1/Datastreams(13)/Observations",
        {"phenomenonTime": ISO, "result": 35},
        1,
    ),
    (
        "solar",
        "inverters",
        {
            "ts": ISO,
            "Inverter_ID": "INV_001_001",
            "Output_AC_Power_kW": 2000,
            "Input_DC_Voltage": 850,
            "Temperature_Module": 45,
            "Efficiency_%": 97.5,
        },
        4,
    ),
]


@pytest.mark.parametrize("source,topic,payload,count", MESSAGES)
def test_sources_preserve_event_and_arrival_time_and_reject_duplicates(
    source, topic, payload, count
):
    normalizer = Normalizer(SELECTION)
    wire = json.dumps(payload).encode()
    result = normalizer.messages(source, topic, wire, received_at=NOW + 1)
    assert len(result) == count
    document = catalogue(SELECTION)
    assert {destination for destination, _ in result} <= {
        reading.topic for reading in document.streams
    }
    for _, encoded in result:
        message = json.loads(encoded)
        assert message["observed_at"] == NOW
        assert message["received_at"] == NOW + 1
        assert message["simulated"] == (source == "solar")
    assert normalizer.messages(source, topic, wire, received_at=NOW + 2) == []


@pytest.mark.parametrize("source,topic,payload,count", MESSAGES)
def test_retained_old_and_future_observations_never_appear_live(
    source, topic, payload, count
):
    normalizer = Normalizer(SELECTION)
    wire = json.dumps(payload).encode()
    assert (
        normalizer.messages(source, topic, wire, received_at=NOW, retained=True) == []
    )
    max_age = MAX_AGE.get(source, DEFAULT_MAX_AGE)
    assert normalizer.messages(source, topic, wire, received_at=NOW + max_age + 1) == []
    assert normalizer.messages(source, topic, wire, received_at=NOW - 11) == []


def test_road_feeds_take_only_the_selected_station_and_known_sensors():
    normalizer = Normalizer(SELECTION)
    reading = json.dumps({"value": 3.0, "time": int(NOW)}).encode()
    for topic in (
        "weather-v2/9999/3",
        "weather-v2/4057/999",
        "weather-v2/status",
        "tms-v2/23438",
    ):
        source = topic.split("-")[0].replace("tms", "traffic")
        assert normalizer.messages(source, topic, reading, received_at=NOW) == []
    status = json.dumps({"updated": int(NOW)}).encode()
    assert (
        normalizer.messages("weather", "weather-v2/status", status, received_at=NOW)
        == []
    )
    assert normalizer.latest == {}
    [(destination, _)] = normalizer.messages(
        "traffic", "tms-v2/23438/5116", reading, received_at=NOW + 300
    )
    assert destination == "demo/traffic/23438/volume_1"


def test_multiplexed_assets_are_not_scored():
    normalizer = Normalizer(SELECTION)
    payload = MESSAGES[3][2] | {"Inverter_ID": "another-inverter"}
    assert (
        normalizer.messages(
            "solar", "inverters", json.dumps(payload).encode(), received_at=NOW
        )
        == []
    )


@pytest.mark.parametrize(
    "wire", [b"no json", b"[]", b"null", b"{}", b'{"VP":null}', b"x" * 65_537]
)
def test_malformed_messages_are_ignored_without_growing_state(wire):
    normalizer = Normalizer(SELECTION)
    assert normalizer.messages("weather", "unexpected", wire, received_at=NOW) == []
    assert normalizer.latest == {}


def test_catalogue_roundtrips_and_changed_entities_get_new_reading_ids():
    document = catalogue(SELECTION)
    assert (
        SystemDocument.model_validate_json(document.model_dump_json(by_alias=True))
        == document
    )
    assert (
        len(document.connections) == len(public_sources()) == len(feeds(SELECTION)) == 4
    )
    assert len(document.streams) == 14
    assert {source["id"] for source in public_sources()} == {
        "weather",
        "traffic",
        "hamburg",
        "solar",
    }
    before = {
        reading.id
        for reading in document.streams
        if reading.connection_id == "demo-weather"
    }
    changed = catalogue(SELECTION.model_copy(update={"weather_station": 1012}))
    after = {
        reading.id
        for reading in changed.streams
        if reading.connection_id == "demo-weather"
    }
    assert before.isdisjoint(after)


@pytest.mark.parametrize("detectors", [[13, 13], [0], [-1], [1, 2, 3, 4]])
def test_detector_selection_is_bounded_positive_and_distinct(detectors):
    with pytest.raises(ValueError):
        FeedSelection(hamburg_detectors=detectors)
