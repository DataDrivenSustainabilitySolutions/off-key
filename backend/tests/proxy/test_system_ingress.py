"""Distinct upstream observations must retain distinct persistence identities."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from off_key_core.db.worker_ownership import WorkerOwnershipLost
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
from off_key_tactic_middleware.config.system_live import SystemLiveSettings
from off_key_tactic_middleware.services.catalogue import system_ingress
from off_key_tactic_middleware.services.catalogue.arrival_cadence import ArrivalCadence
from off_key_tactic_middleware.services.catalogue.broker_access import (
    BrokerRouteAccess,
)

from tests.support.http_source import Reply, http_source


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
        return SimpleNamespace(rc=0, is_published=lambda: True)

    ingress.output = SimpleNamespace(is_connected=lambda: True, publish=publish)
    base_us = int(datetime.now(UTC).timestamp()) * 1_000_000 + 123_456
    clock = iter(base_us + value * clock_step_us for value in range(8))
    monkeypatch.setattr(system_ingress.time, "time", lambda: base_us / 1_000_000)
    monkeypatch.setattr(system_ingress.time, "time_ns", lambda: next(clock) * 1000)
    for value in range(8):
        payload = json.dumps({"temperature": 45 + value, "humidity": 50 + value})
        ingress._receive("test", "broker", "machine/readings", payload.encode(), False)
        await ingress._forward_pending()

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
    writer = DatabaseWriter(config, MagicMock())
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
def test_observation_records_match_the_downstream_message(value):
    """The stored row names the reading the way RADAR reads the published message."""
    catalog = definition()
    stream = catalog.streams()[0]
    observation = Observation(stream, value, datetime.now(UTC), snapshot=False)
    message = observation.message()
    metadata = TopicMetadataExtractor().extract(message.topic, message.payload)
    record = observation.telemetry_record()
    assert metadata is not None
    assert (metadata.charger_id, metadata.telemetry_type) == (
        record.charger_id,
        record.telemetry_type,
    )
    assert message.payload == {
        "value": value,
        "timestamp": record.timestamp.isoformat(),
    }
    assert record.value == float(value)


@pytest.mark.asyncio
async def test_arrival_clock_state_is_bounded_by_configured_topics(monkeypatch):
    monkeypatch.setattr(
        system_ingress, "get_system_live_settings", lambda: SystemLiveSettings()
    )
    ingress = system_ingress.SystemIngress()
    ingress._connect = MagicMock()
    ingress.output = SimpleNamespace(
        is_connected=lambda: True,
        publish=MagicMock(
            return_value=SimpleNamespace(rc=0, is_published=lambda: True)
        ),
    )
    catalog = definition()
    await ingress._configure(catalog)
    clock = int(datetime.now(UTC).timestamp()) * 1_000_000_000
    monkeypatch.setattr(system_ingress.time, "time_ns", lambda: clock)
    payload = b'{"temperature":45,"humidity":50}'
    ingress._receive("test", "broker", "machine/readings", payload, False)
    await ingress._forward_pending()
    first = ingress._received_at_us[("broker", "machine/readings")]
    assert set(ingress.readings) == {"temperature", "humidity"}
    for value in range(100):
        ingress._receive("test", "broker", f"unselected/{value}", payload, False)
        await ingress._forward_pending()
    assert len(ingress._received_at_us) == 1
    assert len(ingress.readings) == 2

    # A revision retaining this input also retains its collision fence.
    catalog.generation = "next"
    await ingress._configure(catalog)
    assert ingress.readings == {}
    ingress._receive("next", "broker", "machine/readings", payload, False)
    await ingress._forward_pending()
    assert ingress._received_at_us[("broker", "machine/readings")] > first
    for stream in catalog.document.streams:
        stream.policy.mode = "off"
    await ingress._configure(catalog)
    assert ingress._received_at_us == {}
    assert ingress.readings == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("retained", "return_code", "active"),
    [(False, 0, True), (True, 0, False), (False, 1, False), (False, 4, False)],
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
        publish=MagicMock(
            return_value=SimpleNamespace(rc=return_code, is_published=lambda: True)
        ),
    )
    await ingress._configure(definition())
    ingress._receive(
        "test",
        "broker",
        "machine/readings",
        b'{"temperature":45,"humidity":50}',
        retained,
    )
    if return_code:
        close = AsyncMock()
        monkeypatch.setattr(system_ingress, "close_client", close)
        with pytest.raises(RuntimeError, match="refused"):
            await ingress._forward_pending()
        close.assert_awaited_once()
        assert ingress.output is None
    else:
        await ingress._forward_pending()
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
        is_connected=lambda: True,
        publish=MagicMock(
            return_value=SimpleNamespace(rc=0, is_published=lambda: True)
        ),
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
        await ingress._forward_pending()
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
        self.topics = topics
        self.credential = credential
        self.proxy = proxy
        self.on_state = on_state
        self.on_message = on_message
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
async def test_a_broker_refusing_clients_while_it_restarts_is_retried(monkeypatch):
    """A refused reconnect used to end recording until someone pressed Reconnect."""
    ingress, now = recording_ingress(
        monkeypatch,
        SYSTEM_COLLECTION_CONNECT_TIMEOUT_SECONDS=60,
        SYSTEM_COLLECTION_RETRY_SECONDS=300,
    )
    await ingress._configure(definition())
    first = FakeWorker.created[0]
    first.on_state("connected", None)
    now[0] = 3600
    first.on_state("reconnecting", "Broker disconnected.")
    # Paho does not reconnect after a refused CONNACK; the worker has given up.
    first.on_state("error", "The broker refused the connection (Server unavailable).")
    assert ingress.states["broker"]["state"] == "error"

    await ingress._supervise()
    assert first.stopped and ingress.workers == []
    assert ingress.states["broker"]["message"].startswith(
        "The broker refused the connection (Server unavailable). It is retried"
    )
    assert ingress.retries["broker"] == 3600 + 300

    # A refused retry keeps its own reason and backs off further.
    now[0] = 3900
    await ingress._supervise()
    retry = FakeWorker.created[1]
    assert retry.started
    retry.on_state("error", "The broker rejected the connection credentials.")
    await ingress._supervise()
    assert retry.stopped
    assert "credentials" in ingress.states["broker"]["message"]
    assert ingress.retries["broker"] == 3900 + 600

    now[0] = 4500
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


@pytest.mark.parametrize(
    ("connected", "generation", "selected", "status"),
    [
        (True, None, True, system_ingress.INGRESS_CONNECTING),
        (True, "previous", True, system_ingress.INGRESS_CONNECTING),
        (True, "test", True, system_ingress.INGRESS_APPLIED),
        (True, None, False, system_ingress.INGRESS_APPLIED),
        (False, "test", True, system_ingress.INGRESS_CONNECTING),
    ],
)
def test_ingress_reports_applied_only_for_the_configured_generation(
    monkeypatch, connected, generation, selected, status
):
    monkeypatch.setattr(
        system_ingress, "get_system_live_settings", lambda: SystemLiveSettings()
    )
    catalog = definition()
    if not selected:
        for stream in catalog.document.streams:
            stream.policy.mode = "off"
    ingress = system_ingress.SystemIngress()
    ingress.output = SimpleNamespace(is_connected=lambda: connected)
    ingress.generation = generation
    assert ingress._status(catalog) == status


@pytest.mark.asyncio
@pytest.mark.parametrize("upstream_retained", [False, True])
async def test_latest_value_survives_activation_and_reconnect_without_new_history(
    monkeypatch, upstream_retained
):
    ingress, _ = recording_ingress(monkeypatch)
    retained = {}
    buffer = CollectionBuffer()

    def publish(topic, envelope, **options):
        assert options["retain"] is True
        if envelope:
            retained[topic] = json.loads(envelope)
            buffer.receive(
                MQTTMessage(topic, retained[topic], datetime.now(UTC), 1, False)
            )
        else:
            retained.pop(topic, None)
        return SimpleNamespace(rc=0, is_published=lambda: True)

    ingress.output = SimpleNamespace(is_connected=lambda: True, publish=publish)
    catalog = definition()
    await ingress._configure(catalog)
    FakeWorker.created[0].on_message(
        "machine/readings", b'{"temperature":45,"humidity":50}', upstream_retained
    )
    await ingress._forward_pending()
    assert buffer.take(now=2) == []  # Collector is still preparing.
    for _ in range(2):  # Activation, then a collector reconnect.
        buffer.configure(catalog, now=0)
        for topic, payload in retained.items():
            buffer.receive(MQTTMessage(topic, payload, datetime.now(UTC), 1, True))
        observations = buffer.take(now=2)
        assert [item.value for item in observations] == [45, 50]
        assert all(item.snapshot for item in observations)
        assert buffer.metrics()["original_queue"] == 0
        buffer.pause()
    catalog.generation = "next"
    await ingress._configure(catalog)
    assert retained == {}


@pytest.mark.asyncio
async def test_retired_client_cannot_forward_queued_or_late_messages(monkeypatch):
    ingress, _ = recording_ingress(monkeypatch)
    ingress.output.publish = MagicMock(
        return_value=SimpleNamespace(rc=0, is_published=lambda: True)
    )
    await ingress._configure(definition())
    retired = FakeWorker.created[0]
    retired.on_message("machine/readings", b'{"temperature":45}', False)
    assert await ingress.reconnect("broker")
    retired.on_message("machine/readings", b'{"temperature":46}', False)
    await ingress._forward_pending()
    ingress.output.publish.assert_not_called()
    assert ingress.readings == {}
    FakeWorker.created[1].on_message("machine/readings", b'{"temperature":47}', False)
    await ingress._forward_pending()
    assert ingress.output.publish.call_count == 2


@pytest.mark.asyncio
async def test_pending_ingress_is_bounded_by_bytes_and_count(monkeypatch):
    ingress, _ = recording_ingress(monkeypatch)
    await ingress._configure(definition())
    monkeypatch.setattr(system_ingress, "MAX_PENDING_MESSAGES", 2)
    worker = FakeWorker.created[0]
    for _ in range(3):
        worker.on_message("machine/readings", b'{"temperature":45}', False)
    assert len(ingress.pending) == 2 and ingress.dropped == 1
    monkeypatch.setattr(system_ingress, "MAX_PENDING_BYTES", ingress.pending_bytes)
    monkeypatch.setattr(system_ingress, "MAX_PENDING_MESSAGES", 10)
    worker.on_message("machine/readings", b'{"temperature":45}', False)
    assert len(ingress.pending) == 2 and ingress.dropped == 2
    await ingress._stop_workers()
    assert not ingress.pending and ingress.pending_bytes == 0


@pytest.mark.asyncio
async def test_lost_owner_cannot_publish_pending_ingress(monkeypatch):
    ingress, _ = recording_ingress(monkeypatch)
    ingress.output.publish = MagicMock()
    await ingress._configure(definition())
    FakeWorker.created[0].on_message("machine/readings", b'{"temperature":45}', False)
    ingress.ownership = SimpleNamespace(
        fence=AsyncMock(side_effect=WorkerOwnershipLost)
    )
    monkeypatch.setattr(
        system_ingress, "get_async_session_local", lambda: lambda: AsyncMock()
    )
    with pytest.raises(WorkerOwnershipLost):
        await ingress._forward_pending()
    ingress.output.publish.assert_not_called()
    assert ingress.readings == {}


def http_definition(port=8080):
    """Two readings of one status reply, one with a source timestamp, and a
    reading of a second path that records every message."""
    document = SystemDocument.model_validate(
        {
            "connections": [
                {
                    "id": "api",
                    "label": "API",
                    "protocol": "http",
                    "host": "127.0.0.1",
                    "port": port,
                }
            ],
            "streams": [
                {
                    "id": "temperature",
                    "label": "Temperature",
                    "connection_id": "api",
                    "topic": "/status",
                    "payload_pointer": "/temperature",
                    "timestamp_pointer": "/measured_at",
                    "policy": {"mode": "sample", "interval_seconds": 30},
                },
                {
                    "id": "humidity",
                    "label": "Humidity",
                    "connection_id": "api",
                    "topic": "/status",
                    "payload_pointer": "/humidity",
                    "policy": {"mode": "sample", "interval_seconds": 5},
                },
                {
                    "id": "power",
                    "label": "Power",
                    "connection_id": "api",
                    "topic": "/meter?phase=1",
                    "policy": {"mode": "original"},
                },
            ],
        }
    )
    return SystemCollectionDefinition(
        document=document, bindings=build_bindings(document), generation="test"
    )


def polling_ingress(monkeypatch, port=8080, **settings):
    FakeWorker.created = []
    monkeypatch.setattr(
        system_ingress,
        "get_system_live_settings",
        lambda: SystemLiveSettings(
            SYSTEM_HTTP_ALLOWED_ORIGINS=[f"http://127.0.0.1:{port}"], **settings
        ),
    )
    monkeypatch.setattr(system_ingress, "LiveMqttWorker", None)
    ingress = system_ingress.SystemIngress()
    published = []

    def publish(topic, envelope, **_):
        published.append((topic, json.loads(envelope)))
        return SimpleNamespace(rc=0, is_published=lambda: True)

    ingress.output = SimpleNamespace(is_connected=lambda: True, publish=publish)
    return ingress, published


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("minimum", "intervals"),
    [
        # The most frequent reading of a path sets its interval; a reading that
        # records every message has no rate of its own and takes the default.
        (1, {"/status": 5, "/meter?phase=1": 10}),
        (20, {"/status": 20, "/meter?phase=1": 20}),
    ],
)
async def test_an_http_source_is_polled_as_often_as_its_readings_record(
    monkeypatch, minimum, intervals
):
    ingress, _ = polling_ingress(monkeypatch, SYSTEM_HTTP_MIN_POLL_SECONDS=minimum)
    monkeypatch.setattr(system_ingress, "HttpPollWorker", FakeWorker)

    await ingress._configure(http_definition())

    (worker,) = FakeWorker.created
    assert worker.started and worker.connection.protocol == "http"
    assert worker.topics == intervals
    assert ingress.states["api"] == {"state": "connecting", "message": None}


@pytest.mark.asyncio
async def test_a_broker_allowlist_does_not_open_an_http_source(monkeypatch):
    ingress, _ = polling_ingress(
        monkeypatch, port=9090, SYSTEM_LIVE_ALLOWED_HOSTS=["127.0.0.1"]
    )
    monkeypatch.setattr(system_ingress, "HttpPollWorker", FakeWorker)

    await ingress._configure(http_definition())

    assert FakeWorker.created == []
    assert ingress.states["api"] == {
        "state": "blocked",
        "message": "Server access is not configured by the operator.",
    }


@pytest.mark.asyncio
async def test_a_poll_without_a_new_source_timestamp_is_not_recorded_again(
    monkeypatch,
):
    ingress, published = polling_ingress(monkeypatch)
    monkeypatch.setattr(system_ingress, "HttpPollWorker", FakeWorker)
    catalog = http_definition()
    await ingress._configure(catalog)
    (worker,) = FakeWorker.created
    topics = {
        stream.definition.id: stream.ingress_topic for stream in catalog.streams()
    }

    async def poll(reply):
        published.clear()
        worker.on_message("/status", json.dumps(reply).encode(), False)
        await ingress._forward_pending()
        return sorted(topic for topic, _ in published)

    both = sorted([topics["temperature"], topics["humidity"]])
    first = {"temperature": 20, "humidity": 40, "measured_at": "2026-11-11T10:00:00Z"}
    assert await poll(first) == both
    # The same measurement again: only the reading without a timestamp records.
    assert await poll({**first, "humidity": 41}) == [topics["humidity"]]
    assert await poll({**first, "measured_at": "2026-11-11T10:00:30Z"}) == both
    # A reply without a readable timestamp counts as new, every time.
    assert await poll({"temperature": 20, "humidity": 40}) == both
    assert await poll({"temperature": 20, "humidity": 40}) == both
    assert await poll(["not", "an", "object"]) == both
    assert ingress.dropped == 0


@pytest.mark.asyncio
async def test_an_http_source_that_gives_up_is_retried_like_a_broker(monkeypatch):
    ingress, _ = polling_ingress(monkeypatch, SYSTEM_COLLECTION_RETRY_SECONDS=300)
    monkeypatch.setattr(system_ingress, "HttpPollWorker", FakeWorker)
    now = [0.0]
    ingress.clock = lambda: now[0]
    await ingress._configure(http_definition())
    (first,) = FakeWorker.created

    first.on_state("error", "The server rejected the connection credentials.")
    await ingress._supervise()
    assert first.stopped and ingress.workers == []
    assert ingress.states["api"] == {
        "state": "error",
        "message": "The server rejected the connection credentials. "
        + system_ingress.RETRY_HINT,
    }

    now[0] = 300
    await ingress._supervise()
    second = FakeWorker.created[1]
    second.on_state("reconnecting", "Server unavailable.")
    now[0] = 400
    await ingress._supervise()
    assert "Could not reach the server within" in ingress.states["api"]["message"]


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_a_polled_http_reply_reaches_the_collector(monkeypatch):
    replies = iter(range(1000))

    def status():
        return Reply(
            body=json.dumps(
                {"temperature": "21.5", "humidity": next(replies), "measured_at": 7}
            ).encode()
        )

    with http_source({"/status": status, "/meter?phase=1": Reply(body=b"230")}) as api:
        ingress, _ = polling_ingress(monkeypatch, port=api.port)
        catalog = http_definition(api.port)
        for stream in catalog.document.streams:
            stream.policy.interval_seconds = 1
        buffer = CollectionBuffer()
        buffer.configure(catalog)

        def publish(topic, envelope, **_):
            buffer.receive(
                MQTTMessage(topic, json.loads(envelope), datetime.now(UTC), 1, False)
            )
            return SimpleNamespace(rc=0, is_published=lambda: True)

        ingress.output = SimpleNamespace(is_connected=lambda: True, publish=publish)
        await ingress._configure(catalog)
        values = {}
        try:
            async with asyncio.timeout(20):
                while len(values.get("humidity", [])) < 2 or "power" not in values:
                    await ingress._forward_pending()
                    for item in buffer.take():
                        values.setdefault(item.stream.definition.id, []).append(
                            item.value
                        )
                    await asyncio.sleep(0.02)
            assert ingress.states["api"] == {"state": "connected", "message": None}
        finally:
            await ingress._stop_workers()

    # A number sent as text is a number, and its unchanged timestamp records once.
    assert values["temperature"] == [21.5]
    # Each later poll is a new observation of the reading without a timestamp.
    assert values["humidity"] == sorted(set(values["humidity"]))
    assert values["power"][0] == 230
    assert set(api.paths()) == {"/status", "/meter?phase=1"}
