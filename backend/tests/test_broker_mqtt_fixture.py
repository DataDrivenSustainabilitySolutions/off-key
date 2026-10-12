"""A mixed topology fixture has one truthful catalog and bounded real publishers."""

import importlib.util
import json
import math
import sys
from collections import Counter
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from off_key_core.schemas.system import SystemDocument

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "broker_fixture", ROOT / "dev/local/broker_fixture.py"
)
fixture = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fixture
SPEC.loader.exec_module(fixture)


def test_catalog_matches_generator_and_has_both_connection_shapes_without_groups():
    raw = json.loads((ROOT / "dev/local/broker-system.json").read_text())
    assert raw == fixture.build_document()
    document = SystemDocument.model_validate(raw)
    assert len(document.connections) == 6
    assert len(document.devices) == 39
    assert len(document.streams) == 300
    assert document.groups == []
    assert sorted(
        Counter(device.connection_id for device in document.devices).values()
    ) == [
        1,
        1,
        1,
        12,
        12,
        12,
    ]
    assert document.default_policy.mode == "off"
    assert all(stream.policy is None for stream in document.streams)
    assert {connection.host for connection in document.connections} == {
        broker.host for broker in fixture.BROKERS
    }
    assert all(connection.credential_ref is None for connection in document.connections)
    by_entity = Counter(stream.device_id for stream in document.streams)
    assert by_entity["fixture:production:station-01"] == 52
    assert by_entity["fixture:meter:main-meter"] == 100
    assert set(by_entity.values()) == {4, 52, 100}
    topics = Counter(
        (stream.connection_id, stream.topic) for stream in document.streams
    )
    assert len(topics) == 183
    assert Counter(topics.values()) == {1: 144, 4: 39}
    assert {stream.category for stream in document.streams} == {
        "Measurement",
        "State",
        "Thermal",
        "Mechanical",
        "Electrical",
        "Diagnostics",
    }


@pytest.mark.parametrize("elapsed", [0, 35, 100, 3600])
def test_every_json_pointer_extracts_the_declared_type_from_one_message(elapsed):
    document = fixture.build_document()
    messages = {
        (publication.broker.id, publication.topic): publication.payload(elapsed)
        for publication in fixture.build_publications()
    }
    assert len(messages) == 183
    for stream in document["streams"]:
        payload = messages[(stream["connection_id"], stream["topic"])]
        value = payload[stream["payload_pointer"][1:]]
        if stream["value_type"] == "number":
            assert type(value) is float and math.isfinite(value)
        elif stream["value_type"] == "boolean":
            assert type(value) is bool
        else:
            assert type(value) is str and value
        assert len(json.dumps(payload)) < 256
    assert len({stream["topic"] for stream in document["streams"]}) == 183


def test_original_stream_identifiers_and_four_field_payloads_stay_compatible():
    document = fixture.build_document()
    streams = {stream["id"]: stream for stream in document["streams"]}
    for broker in fixture.BROKERS:
        for entity in broker.entities:
            for field in ("value", "active", "mode", "sample_id"):
                identifier = f"{fixture.entity_id(broker, entity)}:{field}"
                stream = streams[identifier]
                assert stream["topic"] == fixture.topic(broker, entity)
                assert stream["payload_pointer"] == f"/{field}"


def test_scheduler_bounds_bursts_and_never_replays_missed_intervals():
    publications = fixture.build_publications()
    assert len(publications) == 183
    assert 30 < sum(1 / publication.cadence for publication in publications) < 45
    schedule = fixture.PublishSchedule(publications)
    received = []
    # A long stall must not enqueue hours of historical data. Every topic has
    # at most one pending current reading, released in small, fair batches.
    for _ in range(40):
        batch = schedule.next_batch(3600)
        assert len(batch) <= fixture.MAX_MESSAGES_PER_TICK
        received.extend(publication.topic for publication in batch)
    assert len(received) == len(set(received)) == 183
    assert schedule.next_batch(3600.1) == []
    assert all(publication.sequence == 1 for publication in publications)


def test_regular_scheduler_exercises_every_topic_without_a_publish_flood():
    schedule = fixture.PublishSchedule(fixture.build_publications())
    batches = [schedule.next_batch(tick * fixture.TICK_SECONDS) for tick in range(600)]
    assert all(len(batch) <= 6 for batch in batches)
    assert len({publication.topic for batch in batches for publication in batch}) == 183
    assert 30 < sum(len(batch) for batch in batches) / 60 < 45


@pytest.mark.parametrize("connected", [True, False])
def test_real_publishers_use_only_catalog_topics_and_bounded_nonretained_messages(
    monkeypatch,
    tmp_path,
    connected,
):
    import paho.mqtt.client as mqtt

    clients = []

    def client_factory(**kwargs):
        client = MagicMock()
        client.is_connected.return_value = connected
        clients.append(client)
        return client

    event = MagicMock()
    ticks = 400
    event.is_set.side_effect = [False] * ticks + [True]
    monkeypatch.setattr(fixture.threading, "Event", lambda: event)
    monkeypatch.setattr(fixture.signal, "signal", lambda *_: None)
    times = iter([0.0] + [index * fixture.TICK_SECONDS for index in range(ticks)])
    monkeypatch.setattr(fixture.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(fixture, "HEARTBEAT", tmp_path / "ready")
    monkeypatch.setattr(mqtt, "Client", client_factory)
    fixture.publish()
    assert len(clients) == 6
    assert not fixture.HEARTBEAT.exists()
    assert sum(client.publish.call_count for client in clients) <= ticks * 6
    document = fixture.build_document()
    for broker, client in zip(fixture.BROKERS, clients, strict=True):
        client.connect_async.assert_called_once_with(broker.host, 1883, keepalive=30)
        client.max_queued_messages_set.assert_called_once_with(64)
        client.max_inflight_messages_set.assert_called_once_with(8)
        expected_topics = {
            stream["topic"]
            for stream in document["streams"]
            if stream["connection_id"] == broker.id
        }
        assert {call.args[0] for call in client.publish.call_args_list} == (
            expected_topics if connected else set()
        )
        for call in client.publish.call_args_list:
            assert call.kwargs == {"qos": 0, "retain": False}
            expected_keys = (
                {"value", "active", "mode", "sample_id"}
                if call.args[0].endswith("/telemetry")
                else {"value"}
            )
            assert set(json.loads(call.args[1])) == expected_keys
        client.disconnect.assert_called_once()
        client.loop_stop.assert_called_once()
