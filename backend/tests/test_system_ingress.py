"""Distinct upstream observations must retain distinct persistence identities."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from off_key_core.schemas.system import SystemDocument
from off_key_core.schemas.system_collection import (
    SystemCollectionDefinition,
    build_bindings,
)
from off_key_core.utils.mqtt_topics import TopicMetadataExtractor
from off_key_mqtt_proxy.client.models import MQTTMessage
from off_key_mqtt_proxy.collection_buffer import CollectionBuffer
from off_key_mqtt_proxy.config.config import MQTTSettings
from off_key_mqtt_proxy.telemetry import DatabaseWriter
from off_key_tactic_middleware.config.system_live import SystemLiveSettings
from off_key_tactic_middleware.services import system_ingress


def definition():
    document = SystemDocument.model_validate(
        {
            "connections": [{"id": "broker", "label": "Broker", "host": "127.0.0.1"}],
            "streams": [
                {
                    "id": name,
                    "label": name.title(),
                    "connection_id": "broker",
                    "topic": "machine/readings",
                    "payload_pointer": f"/{name}",
                    "policy": {"mode": "original"},
                }
                for name in ("temperature", "humidity")
            ],
        }
    )
    return SystemCollectionDefinition(
        document=document, bindings=build_bindings(document), generation="test"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("clock_step_us", [0, 1])
async def test_original_burst_preserves_every_writer_identity(
    monkeypatch, clock_step_us
):
    catalog = definition()
    monkeypatch.setattr(
        system_ingress, "get_system_live_settings", lambda: SystemLiveSettings()
    )
    ingress = system_ingress.SystemIngress()
    ingress.generation = catalog.generation
    ingress.bindings = {"broker": {"machine/readings": catalog.streams()}}
    envelopes = []

    def publish(topic, envelope, **_):
        envelopes.append(
            MQTTMessage(topic, json.loads(envelope), datetime.now(UTC), 1, False)
        )
        return SimpleNamespace(rc=0)

    ingress.output = SimpleNamespace(is_connected=lambda: True, publish=publish)
    base_us = int(datetime.now(UTC).timestamp()) * 1_000_000 + 123_456
    clock = iter(base_us + value * clock_step_us for value in range(8))
    monkeypatch.setattr(system_ingress.time, "time", lambda: base_us / 1_000_000)
    monkeypatch.setattr(system_ingress.time, "time_ns", lambda: next(clock) * 1000)
    for value in range(8):
        payload = json.dumps({"temperature": 45 + value, "humidity": 50 + value})
        ingress._receive("test", "broker", "machine/readings", payload.encode(), False)

    buffer = CollectionBuffer()
    buffer.configure(catalog)
    for envelope in envelopes:
        buffer.receive(envelope)
    observations = buffer.take()
    assert [item.value for item in observations] == [
        value for step in range(8) for value in (45 + step, 50 + step)
    ]
    timestamps = [item.received_at for item in observations]
    # Fields from one upstream message remain aligned; separate arrivals do not
    # collide with the (entity, timestamp, reading) database uniqueness constraint.
    assert timestamps[::2] == timestamps[1::2]
    assert len(set(timestamps[::2])) == 8
    assert timestamps[0] == datetime.fromtimestamp(base_us / 1_000_000, UTC)

    config = MQTTSettings(
        MQTT_USE_AUTH=False, MQTT_USE_TLS=False, ENVIRONMENT="development"
    ).config
    writer = DatabaseWriter(config, MagicMock(), TopicMetadataExtractor())
    for observation in observations:
        await writer.write_telemetry_message(observation.message())
    records = [record.to_dict() for record in writer.pending_batch.records]
    assert len(records) == 16
    assert (
        len(
            {
                (record["charger_id"], record["timestamp"], record["type"])
                for record in records
            }
        )
        == 16
    )


@pytest.mark.asyncio
async def test_arrival_clock_state_is_bounded_by_configured_topics(monkeypatch):
    monkeypatch.setattr(
        system_ingress, "get_system_live_settings", lambda: SystemLiveSettings()
    )
    ingress = system_ingress.SystemIngress()
    ingress._connect = MagicMock()
    ingress.output = SimpleNamespace(
        is_connected=lambda: True, publish=MagicMock(return_value=SimpleNamespace(rc=0))
    )
    catalog = definition()
    await ingress._configure(catalog)
    clock = int(datetime.now(UTC).timestamp()) * 1_000_000_000
    monkeypatch.setattr(system_ingress.time, "time_ns", lambda: clock)
    payload = b'{"temperature":45,"humidity":50}'
    ingress._receive("test", "broker", "machine/readings", payload, False)
    first = ingress._received_at_us[("broker", "machine/readings")]
    for value in range(100):
        ingress._receive("test", "broker", f"unselected/{value}", payload, False)
    assert len(ingress._received_at_us) == 1

    # A revision retaining this input also retains its collision fence.
    catalog.generation = "next"
    await ingress._configure(catalog)
    ingress._receive("next", "broker", "machine/readings", payload, False)
    assert ingress._received_at_us[("broker", "machine/readings")] > first
    for stream in catalog.document.streams:
        stream.policy.mode = "off"
    await ingress._configure(catalog)
    assert ingress._received_at_us == {}
