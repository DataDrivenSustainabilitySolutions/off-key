"""Provider-shaped messages must become stable, fresh application readings."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from off_key_core.demo.catalogue import MOSQUITTO_SENSORS, FeedSelection, catalogue
from off_key_core.demo.sources import public_sources
from off_key_core.schemas.system import SystemDocument
from off_key_mqtt_proxy.demo import probe as live_probe
from off_key_mqtt_proxy.demo.normalize import DEFAULT_MAX_AGE, MAX_AGE, Normalizer
from off_key_mqtt_proxy.demo.relay import feeds

NOW = 1_794_475_800.0
SELECTION = FeedSelection()
MESSAGES = [
    (
        "weather",
        "weather-v2/1003/3",
        {"value": -1.4, "time": int(NOW)},
        1,
    ),
    (
        "traffic",
        "tms-v2/23438/5122",
        {"value": 87, "time": int(NOW), "start": int(NOW) - 300, "end": int(NOW)},
        1,
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
        assert message["simulated"] is False
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
        "weather-v2/1003/999",
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


@pytest.mark.parametrize("field,mqtt_topic", MOSQUITTO_SENSORS.items())
def test_broker_metrics_record_only_fresh_numeric_updates(field, mqtt_topic):
    normalizer = Normalizer(SELECTION)
    assert (
        normalizer.messages(
            "mosquitto", mqtt_topic, b"12606", received_at=NOW, retained=True
        )
        == []
    )
    [(destination, encoded)] = normalizer.messages(
        "mosquitto", mqtt_topic, b"12606", received_at=NOW
    )
    assert destination == f"demo/mosquitto/test-mosquitto-org/{field}"
    message = json.loads(encoded)
    assert message["value"] == 12606
    assert message["observed_at"] is None
    assert message["received_at"] == NOW
    assert message["simulated"] is False
    assert normalizer.messages("mosquitto", mqtt_topic, b"12606", received_at=NOW) == []
    assert normalizer.messages("mosquitto", mqtt_topic, b"12607", received_at=NOW + 10)


@pytest.mark.parametrize(
    "wire", [b"true", b"null", b"{}", b"[]", b'"12"', b"-1", b"NaN", b"Infinity"]
)
def test_broker_metrics_reject_invalid_values_and_unknown_topics(wire):
    normalizer = Normalizer(SELECTION)
    assert (
        normalizer.messages(
            "mosquitto", "$SYS/broker/clients/connected", wire, received_at=NOW
        )
        == []
    )
    assert (
        normalizer.messages("mosquitto", "someone/clients", b"12", received_at=NOW)
        == []
    )
    assert normalizer.latest == {}


def test_discovery_uses_supported_network_topics_then_pins_the_fresh_station(
    monkeypatch,
):
    clients = {}
    monkeypatch.setattr(live_probe.time, "time", lambda: NOW)

    def subscribe(feed, receive):
        client = clients[feed.id] = Mock()
        # Digitraffic's network-wide subscription delivers measurements; the
        # unsupported '+' variant used to leave discovery at an invalid default.
        observations = {
            "weather": ("weather-v2/#", "weather-v2/1001/1"),
            "traffic": ("tms-v2/#", "tms-v2/23439/5122"),
        }
        if feed.id in observations:
            subscription, mqtt_topic = observations[feed.id]
            if subscription in feed.topics:
                receive(
                    client,
                    None,
                    SimpleNamespace(
                        retain=False,
                        topic=mqtt_topic,
                        payload=json.dumps({"time": NOW, "value": 1.3}).encode(),
                    ),
                )
        return client

    monkeypatch.setattr(live_probe, "subscriber", subscribe)
    selected = live_probe.probe(SELECTION, seconds=0, discover=True)
    assert selected.weather_station == 1001
    assert selected.traffic_station == 23439
    clients["weather"].unsubscribe.assert_called_once_with(["weather-v2/#"])
    subscriptions = clients["weather"].subscribe.call_args.args[0]
    assert ("weather-v2/1001/1", 0) in subscriptions
    assert ("weather-v2/status", 0) in subscriptions


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
        len(document.connections) == len(public_sources()) == len(feeds(SELECTION)) == 3
    )
    assert len(document.streams) == 12
    assert {source["id"] for source in public_sources()} == {
        "weather",
        "traffic",
        "mosquitto",
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
