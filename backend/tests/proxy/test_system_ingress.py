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
from off_key_mqtt_proxy.collection_buffer import CollectionBuffer, Observation
from off_key_mqtt_proxy.config.config import MQTTSettings
from off_key_mqtt_proxy.telemetry import DatabaseWriter
from off_key_mqtt_proxy.telemetry_parsing import parse_telemetry_message
from off_key_tactic_middleware.config.system_live import SystemLiveSettings
from off_key_tactic_middleware.services.catalogue import system_ingress
from off_key_tactic_middleware.services.catalogue.arrival_cadence import ArrivalCadence
from off_key_tactic_middleware.services.catalogue.broker_access import (
    BrokerRouteAccess,
)


def definition(host="127.0.0.1"):
    document = SystemDocument.model_validate(
        {
            "connections": [{"id": "broker", "label": "Broker", "host": host}],
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
        await writer.write_record(observation.telemetry_record())
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


@pytest.mark.parametrize("value", [42, 42.5, -0.25])
def test_observation_records_match_the_parsed_downstream_message(value):
    """Direct records equal what the regex parser reads back from the message."""
    catalog = definition()
    stream = catalog.streams()[0]
    observation = Observation(stream, value, datetime.now(UTC), snapshot=False)
    extractor = MQTTSettings(
        MQTT_USE_AUTH=False, MQTT_USE_TLS=False, ENVIRONMENT="development"
    ).config.build_topic_extractor()
    parsed = parse_telemetry_message(observation.message(), extractor).record
    record = observation.telemetry_record(created=parsed.created)
    assert record == parsed


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
    assert set(ingress.readings) == {"temperature", "humidity"}
    for value in range(100):
        ingress._receive("test", "broker", f"unselected/{value}", payload, False)
    assert len(ingress._received_at_us) == 1
    assert len(ingress.readings) == 2

    # A revision retaining this input also retains its collision fence.
    catalog.generation = "next"
    await ingress._configure(catalog)
    assert ingress.readings == {}
    ingress._receive("next", "broker", "machine/readings", payload, False)
    assert ingress._received_at_us[("broker", "machine/readings")] > first
    for stream in catalog.document.streams:
        stream.policy.mode = "off"
    await ingress._configure(catalog)
    assert ingress._received_at_us == {}
    assert ingress.readings == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("retained", "return_code", "active"),
    [(False, 0, True), (True, 0, False), (False, 1, False)],
)
async def test_activity_requires_a_fresh_successfully_forwarded_message(
    monkeypatch, retained, return_code, active
):
    monkeypatch.setattr(
        system_ingress, "get_system_live_settings", lambda: SystemLiveSettings()
    )
    ingress = system_ingress.SystemIngress()
    ingress._connect = MagicMock()
    ingress.output = SimpleNamespace(
        is_connected=lambda: True,
        publish=MagicMock(return_value=SimpleNamespace(rc=return_code)),
    )
    await ingress._configure(definition())
    ingress._receive(
        "test",
        "broker",
        "machine/readings",
        b'{"temperature":45,"humidity":50}',
        retained,
    )
    assert bool(ingress.readings) is active
    if active:
        assert set(ingress.readings) == {"temperature", "humidity"}
        assert (
            ingress.readings["temperature"]["fresh_received_at"]
            == ingress.readings["humidity"]["fresh_received_at"]
        )
    await ingress._stop_workers()
    assert ingress.readings == {}


@pytest.mark.asyncio
async def test_activity_reports_each_readings_typical_arrival_interval(monkeypatch):
    monkeypatch.setattr(
        system_ingress, "get_system_live_settings", lambda: SystemLiveSettings()
    )
    ingress = system_ingress.SystemIngress()
    ingress._connect = MagicMock()
    ingress.output = SimpleNamespace(
        is_connected=lambda: True, publish=MagicMock(return_value=SimpleNamespace(rc=0))
    )
    await ingress._configure(definition())
    start = int(datetime.now(UTC).timestamp()) * 1_000_000_000
    payload = b'{"temperature":45,"humidity":50}'
    # A source reporting every three minutes, with one rare outage in between.
    for minutes in (*range(0, 31, 3), 54):
        monkeypatch.setattr(
            system_ingress.time, "time_ns", lambda m=minutes: start + m * 60 * 10**9
        )
        ingress._receive("test", "broker", "machine/readings", payload, False)
    assert ingress.readings["temperature"]["typical_interval_seconds"] == 180
    assert ingress.readings["humidity"]["typical_interval_seconds"] == 180


def test_arrival_cadence_needs_two_arrivals_and_ignores_repeats():
    cadence = ArrivalCadence()
    cadence.add(10.0)
    assert cadence.typical_seconds is None
    cadence.add(10.0)
    assert cadence.typical_seconds is None
    cadence.add(70.0)
    assert cadence.typical_seconds == 60


def test_arrival_cadence_learns_the_pauses_of_a_bursty_source():
    cadence = ArrivalCadence()
    at = 0.0
    # Eight quick reports on every change, then a five-minute pause.
    for _ in range(5):
        for _ in range(8):
            at += 0.2
            cadence.add(at)
        at += 300
    cadence.add(at)
    assert cadence.typical_seconds >= 300


class FakeWorker:
    def __init__(
        self, connection, topics, credential, on_message, on_state, proxy=None, **_
    ):
        self.connection = connection
        self.credential = credential
        self.proxy = proxy
        self.on_state = on_state
        self.started = False
        self.stopped = False
        FakeWorker.created.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


def recording_ingress(monkeypatch, **settings):
    FakeWorker.created = []
    monkeypatch.setattr(
        system_ingress,
        "get_system_live_settings",
        lambda: SystemLiveSettings(SYSTEM_LIVE_ALLOWED_HOSTS=["127.0.0.1"], **settings),
    )
    monkeypatch.setattr(system_ingress, "LiveMqttWorker", FakeWorker)
    now = [0.0]
    ingress = system_ingress.SystemIngress(clock=lambda: now[0])
    ingress.output = SimpleNamespace(is_connected=lambda: True)
    return ingress, now


@pytest.mark.asyncio
async def test_an_unreachable_broker_stops_reconnecting_after_its_deadline(
    monkeypatch,
):
    ingress, now = recording_ingress(
        monkeypatch,
        SYSTEM_COLLECTION_CONNECT_TIMEOUT_SECONDS=60,
        SYSTEM_COLLECTION_RETRY_SECONDS=300,
    )
    await ingress._configure(definition())
    first = FakeWorker.created[0]
    first.on_state("reconnecting", "Broker unavailable.")
    now[0] = 59
    first.on_state("reconnecting", "Still unavailable.")  # Retries never extend it.
    await ingress._supervise()
    assert ingress.states["broker"]["state"] == "reconnecting"

    now[0] = 60
    await ingress._supervise()
    assert first.stopped
    assert ingress.workers == []
    assert ingress.states["broker"]["state"] == "error"
    assert "60 seconds" in ingress.states["broker"]["message"]
    # A late callback of the stopped client cannot revive "reconnecting".
    first.on_state("reconnecting", "Late.")
    assert ingress.states["broker"]["state"] == "error"

    # The quiet retry keeps reporting the failure until it connects.
    now[0] = 359
    await ingress._supervise()
    assert len(FakeWorker.created) == 1
    now[0] = 360
    await ingress._supervise()
    retry = FakeWorker.created[1]
    assert retry.started
    retry.on_state("reconnecting", "Broker unavailable.")
    assert ingress.states["broker"]["state"] == "error"

    # Each failed retry doubles the wait.
    now[0] = 420
    await ingress._supervise()
    assert retry.stopped
    assert ingress.retries["broker"] == 420 + 600

    now[0] = 1020
    await ingress._supervise()
    FakeWorker.created[2].on_state("connected", None)
    assert ingress.states["broker"] == {"state": "connected", "message": None}
    assert ingress.deadlines == {} and ingress.failures == {}


@pytest.mark.asyncio
async def test_a_connected_broker_tolerates_short_outages(monkeypatch):
    ingress, now = recording_ingress(
        monkeypatch, SYSTEM_COLLECTION_CONNECT_TIMEOUT_SECONDS=60
    )
    await ingress._configure(definition())
    worker = FakeWorker.created[0]
    worker.on_state("connected", None)
    now[0] = 600
    await ingress._supervise()
    worker.on_state("reconnecting", "Broker disconnected.")
    now[0] = 650
    worker.on_state("connected", None)
    now[0] = 700
    await ingress._supervise()
    assert not worker.stopped
    assert ingress.states["broker"]["state"] == "connected"


@pytest.mark.asyncio
async def test_reconnect_replaces_the_client_and_resets_backoff(monkeypatch):
    ingress, now = recording_ingress(
        monkeypatch, SYSTEM_COLLECTION_CONNECT_TIMEOUT_SECONDS=60
    )
    assert not await ingress.reconnect("broker")
    await ingress._configure(definition())
    first = FakeWorker.created[0]
    now[0] = 60
    await ingress._supervise()
    assert ingress.states["broker"]["state"] == "error"

    assert await ingress.reconnect("broker")
    assert ingress.states["broker"]["state"] == "connecting"
    assert ingress.retries == {} and ingress.failures == {}
    second = FakeWorker.created[1]
    assert second.started and ingress.workers == [second]
    assert ingress.deadlines["broker"] == 120

    # Reconnecting while a client still retries replaces that client too.
    second.on_state("reconnecting", "Broker unavailable.")
    assert await ingress.reconnect("broker")
    assert second.stopped and first.started is not False
    second.on_state("connected", None)
    assert ingress.states["broker"]["state"] == "connecting"
    assert not await ingress.reconnect("other")


@pytest.mark.asyncio
async def test_persistent_collection_reaches_covered_brokers_through_the_route(
    monkeypatch,
):
    FakeWorker.created = []
    settings = SystemLiveSettings(
        SYSTEM_BROKER_ROUTES=json.dumps(
            [
                {
                    "name": "partner",
                    "host_suffixes": [".mesh.example"],
                    "socks_proxy": {"host": "broker-route", "port": 1055},
                    "credential": {"username": "operator", "password": "secret"},
                }
            ]
        )
    )
    monkeypatch.setattr(system_ingress, "get_system_live_settings", lambda: settings)
    monkeypatch.setattr(system_ingress, "LiveMqttWorker", FakeWorker)
    ingress = system_ingress.SystemIngress(access_resolver=BrokerRouteAccess(settings))
    ingress.output = SimpleNamespace(is_connected=lambda: True)

    await ingress._configure(definition("charger.mesh.example"))
    worker = FakeWorker.created[0]
    assert worker.started
    assert (worker.proxy.host, worker.proxy.port) == ("broker-route", 1055)
    assert worker.credential.username == "operator"
    assert ingress.states["broker"]["state"] == "connecting"

    await ingress._configure(definition("other.example"))
    assert len(FakeWorker.created) == 1
    assert ingress.states["broker"]["state"] == "blocked"
