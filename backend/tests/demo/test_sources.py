"""Provider-shaped messages must become stable, fresh application readings."""

import json
from datetime import UTC, datetime

import pytest
from off_key_core.demo.catalogue import FeedSelection, catalogue
from off_key_core.demo.sources import public_sources
from off_key_core.schemas.system import SystemDocument
from off_key_mqtt_proxy.demo.normalize import Normalizer
from off_key_mqtt_proxy.demo.relay import feeds

NOW = 1_794_475_800.0
ISO = datetime.fromtimestamp(NOW, UTC).isoformat()
SELECTION = FeedSelection()
MESSAGES = [
    (
        "hsl",
        "/hfp/v2/journey/ongoing/vp/tram/0040/00639/route/location",
        {
            "VP": {
                "oper": 40,
                "veh": 639,
                "tst": ISO,
                "spd": 7.5,
                "acc": -0.2,
                "dl": -30,
                "drst": 0,
            }
        },
        4,
    ),
    (
        "hamburg",
        "v1.1/Datastreams(13)/Observations",
        {"phenomenonTime": ISO, "result": 35},
        1,
    ),
    (
        "marine",
        "vessels-v2/372777000/location",
        {"time": NOW * 1000, "sog": 12.1, "cog": 42, "heading": 41},
        3,
    ),
    (
        "rail",
        "train-locations/2026-11-12/38",
        {"timestamp": ISO, "trainNumber": 38, "speed": 130},
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
    assert normalizer.messages(source, topic, wire, received_at=NOW + 121) == []
    assert normalizer.messages(source, topic, wire, received_at=NOW - 11) == []


def test_moving_hsl_topics_do_not_duplicate_or_change_entity():
    normalizer = Normalizer(SELECTION)
    source, topic, payload, _ = MESSAGES[0]
    wire = json.dumps(payload).encode()
    assert len(normalizer.messages(source, topic, wire, received_at=NOW)) == 4
    assert normalizer.messages(source, topic + "/moved", wire, received_at=NOW) == []
    payload = {"VP": payload["VP"] | {"veh": 640}}
    assert (
        normalizer.messages(
            source, topic, json.dumps(payload).encode(), received_at=NOW
        )
        == []
    )


def test_multiplexed_assets_and_ais_unavailable_values_are_not_scored():
    normalizer = Normalizer(SELECTION)
    payload = MESSAGES[4][2] | {"Inverter_ID": "another-inverter"}
    assert (
        normalizer.messages(
            "solar", "inverters", json.dumps(payload).encode(), received_at=NOW
        )
        == []
    )
    payload = MESSAGES[2][2] | {"sog": 102.3, "cog": 360, "heading": 511}
    assert (
        normalizer.messages(
            "marine", MESSAGES[2][1], json.dumps(payload).encode(), received_at=NOW
        )
        == []
    )


@pytest.mark.parametrize(
    "wire", [b"no json", b"[]", b"null", b"{}", b'{"VP":null}', b"x" * 65_537]
)
def test_malformed_messages_are_ignored_without_growing_state(wire):
    normalizer = Normalizer(SELECTION)
    assert normalizer.messages("hsl", "unexpected", wire, received_at=NOW) == []
    assert normalizer.latest == {}


def test_catalogue_roundtrips_and_changed_entities_get_new_reading_ids():
    document = catalogue(SELECTION)
    assert (
        SystemDocument.model_validate_json(document.model_dump_json(by_alias=True))
        == document
    )
    assert (
        len(document.connections) == len(public_sources()) == len(feeds(SELECTION)) == 5
    )
    assert len(document.streams) == 14
    assert {source["id"] for source in public_sources()} == {
        "hsl",
        "hamburg",
        "marine",
        "rail",
        "solar",
    }
    before = {
        reading.id
        for reading in document.streams
        if reading.connection_id == "demo-hsl"
    }
    changed = catalogue(SELECTION.model_copy(update={"hsl_vehicle": "0040/00640"}))
    after = {
        reading.id for reading in changed.streams if reading.connection_id == "demo-hsl"
    }
    assert before.isdisjoint(after)


@pytest.mark.parametrize("detectors", [[13, 13], [0], [-1], [1, 2, 3, 4]])
def test_detector_selection_is_bounded_positive_and_distinct(detectors):
    with pytest.raises(ValueError):
        FeedSelection(hamburg_detectors=detectors)
