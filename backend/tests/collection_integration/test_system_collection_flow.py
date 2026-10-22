"""Real generic MQTT -> EMQX -> opt-in collector -> history integration."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
import pytest_asyncio
from off_key_core.db.collection_runtime import read_collection_runtime
from off_key_core.db.models import CollectionState, Telemetry
from off_key_core.schemas.collection_policy import CollectionPolicy
from off_key_core.schemas.collection_rules import (
    CollectionRuleEdit,
    CollectionRuleScope,
    SystemCollectionRuleChange,
)
from off_key_core.schemas.system import SystemChange, SystemDocument
from off_key_core.schemas.system_collection import SystemCollectionChange
from off_key_core.utils.mqtt_topics import TopicMetadataExtractor
from off_key_mqtt_proxy import proxy as proxy_module
from off_key_mqtt_proxy.config.config import MQTTSettings
from off_key_mqtt_radar.topic_parser import TopicParser
from off_key_tactic_middleware.config.system_live import SystemLiveSettings
from off_key_tactic_middleware.services import system_collection as collection_module
from off_key_tactic_middleware.services import system_ingress as ingress_module
from off_key_tactic_middleware.services.system import SystemService
from off_key_tactic_middleware.services.system_live import SystemLiveService
from paho.mqtt.client import CallbackAPIVersion, Client
from paho.mqtt.publish import multiple, single
from sqlalchemy import func, select

from . import environment as fixture

pytestmark = fixture.pytestmark
until = fixture.until


@pytest_asyncio.fixture
async def database_session(monkeypatch):
    async with asynccontextmanager(fixture.database.__wrapped__)(monkeypatch) as value:
        yield value


async def collection_applied(sessions, ingress, *, idle=False):
    async with sessions() as session:
        runtime = await read_collection_runtime(session)
        return (
            runtime.collection.get("revision") == runtime.revision
            and runtime.collection.get("status") == "applied"
            and (not ingress.workers if idle else bool(ingress.workers))
            and all(state["state"] == "connected" for state in ingress.states.values())
        )


@pytest.mark.asyncio
async def test_generic_collection_is_independent_of_view_leases_and_stops_on_off(
    monkeypatch, database_session
):
    engine, sessions = database_session
    settings = SystemLiveSettings(
        SYSTEM_LIVE_ENABLED=True, SYSTEM_LIVE_ALLOWED_HOSTS=["127.0.0.1"]
    )
    for module in (proxy_module, ingress_module):
        monkeypatch.setattr(module, "get_async_engine", lambda: engine)
        monkeypatch.setattr(module, "get_async_session_local", lambda: sessions)
    for module in (collection_module, ingress_module):
        monkeypatch.setattr(module, "get_system_live_settings", lambda: settings)
    monkeypatch.setattr(
        ingress_module,
        "get_tactic_settings",
        lambda: SimpleNamespace(
            config=SimpleNamespace(
                radar_defaults=SimpleNamespace(
                    mqtt_broker_host="127.0.0.1",
                    mqtt_broker_port=28883,
                    mqtt_use_auth=False,
                    mqtt_use_tls=False,
                )
            )
        ),
    )
    monkeypatch.setattr(
        proxy_module,
        "get_mqtt_settings",
        lambda: MQTTSettings(
            MQTT_BROKER_HOST="127.0.0.1",
            MQTT_BROKER_PORT=28883,
            MQTT_USE_AUTH=False,
            MQTT_USE_TLS=False,
            ENVIRONMENT="development",
            MQTT_BATCH_TIMEOUT=0.1,
            MQTT_CONNECTION_TIMEOUT=5,
        ),
    )
    doc = SystemDocument.model_validate(
        {
            "connections": [
                {
                    "id": "factory",
                    "label": "Factory",
                    "host": "127.0.0.1",
                    "port": 28884,
                }
            ],
            "devices": [
                {"id": "machine", "label": "Machine", "connection_id": "factory"}
            ],
            "streams": [
                {
                    "id": "temperature",
                    "label": "Temperature",
                    "connection_id": "factory",
                    "device_id": "machine",
                    "topic": "factory/machine/readings",
                    "payload_pointer": "/temperature",
                },
                {
                    "id": "humidity",
                    "label": "Humidity",
                    "connection_id": "factory",
                    "device_id": "machine",
                    "topic": "factory/machine/readings",
                    "payload_pointer": "/humidity",
                },
                {
                    "id": "running",
                    "label": "Running",
                    "connection_id": "factory",
                    "device_id": "machine",
                    "topic": "factory/machine/readings",
                    "payload_pointer": "/running",
                    "value_type": "boolean",
                },
            ],
        }
    )
    async with sessions.begin() as session:
        saved = await SystemService(session).save(
            SystemChange(expected_revision=0, document=doc),
            actor="integration@example.com",
        )
    collector = proxy_module.MQTTProxyService()
    ingress = ingress_module.SystemIngress()
    viewer = SystemLiveService(settings)
    accepted = []
    client = Client(
        CallbackAPIVersion.VERSION2, client_id="generic-integration-detector"
    )
    client.on_connect = lambda client, *args: client.subscribe("telemetry/#")
    client.on_message = lambda client, userdata, message: accepted.append(
        (message.topic, json.loads(message.payload))
    )
    await asyncio.to_thread(client.connect, "127.0.0.1", 28883)
    client.loop_start()

    async def rows():
        async with sessions() as session:
            return await session.scalar(select(func.count()).select_from(Telemetry))

    async def publish(value):
        await asyncio.to_thread(
            single,
            "factory/machine/readings",
            readings(value),
            hostname="127.0.0.1",
            port=28884,
        )

    async def policy(ids, mode, interval=1):
        async with sessions.begin() as session:
            snapshot = await SystemService(session).read()
            return await SystemService(session).apply_collection(
                SystemCollectionChange(
                    expected_revision=snapshot.revision,
                    expected_collection_revision=snapshot.runtime.collection_revision,
                    stream_ids=ids,
                    policy=CollectionPolicy(mode=mode, interval_seconds=interval),
                ),
                actor="integration@example.com",
            )

    try:
        await ingress.start()
        # A temporary live view receives data without creating recorded telemetry.
        lease = await viewer.acquire(saved, 1, saved.revision, ["temperature"])
        await asyncio.sleep(0.3)
        for value in range(3):
            await publish(20 + value)
            await asyncio.sleep(0.2)
        assert await rows() == 0 and accepted == []
        assert viewer.snapshot(0)["samples"]
        await viewer.release(1, lease["lease_id"])
        assert not viewer.workers
        async with sessions.begin() as session:
            snapshot = await SystemService(session).read()
            await SystemService(session).apply_collection(
                SystemCollectionRuleChange(
                    expected_revision=snapshot.revision,
                    expected_collection_revision=snapshot.runtime.collection_revision,
                    rule_changes=[
                        CollectionRuleEdit(
                            scope=CollectionRuleScope(
                                kind="topic",
                                connection_id="factory",
                                topic_prefix="factory/machine",
                            ),
                            policy=CollectionPolicy(mode="sample", interval_seconds=1),
                        ),
                        CollectionRuleEdit(
                            scope=CollectionRuleScope(
                                kind="reading",
                                connection_id="factory",
                                reading_id="humidity",
                            ),
                            policy=CollectionPolicy(mode="off"),
                        ),
                    ],
                ),
                actor="integration@example.com",
            )
        await collector.start()
        await until(lambda: collection_applied(sessions, ingress))
        for value in range(5):
            await publish(25 + value)
            await asyncio.sleep(0.25)
        await until(lambda: has_rows(rows))
        assert accepted
        topic, payload = accepted[-1]
        binding = TopicMetadataExtractor().extract(topic)
        assert binding and TopicParser.extract_charger_id(topic) == binding.charger_id
        assert TopicParser.extract_sensor_type(topic) == binding.telemetry_type
        assert isinstance(payload["value"], (int, float))
        assert await rows() <= 3
        async with sessions() as session:
            states = list(await session.scalars(select(CollectionState)))
            assert any(state.value is True for state in states)
        # A future catalogue field stays Off until this parent explicitly admits it.
        async with sessions.begin() as session:
            snapshot = await SystemService(session).read()
            addition = snapshot.document.model_copy(deep=True)
            addition.streams.append(
                addition.streams[0].model_copy(
                    update={
                        "id": "voltage",
                        "label": "Voltage",
                        "payload_pointer": "/voltage",
                    }
                )
            )
            snapshot = await SystemService(session).save(
                SystemChange(expected_revision=snapshot.revision, document=addition),
                actor="integration@example.com",
            )
            assert snapshot.runtime.bindings["voltage"]["policy"]["mode"] == "off"
            assert snapshot.runtime.bindings["voltage"]["policy_origin"]["needs_review"]
            voltage_topic = snapshot.runtime.bindings["voltage"]["accepted_topic"]
        await until(lambda: collection_applied(sessions, ingress))
        await publish(31)
        await asyncio.sleep(1.2)
        assert all(topic != voltage_topic for topic, _ in accepted)
        async with sessions.begin() as session:
            snapshot = await SystemService(session).read()
            await SystemService(session).apply_collection(
                SystemCollectionRuleChange(
                    expected_revision=snapshot.revision,
                    expected_collection_revision=snapshot.runtime.collection_revision,
                    rule_changes=[
                        CollectionRuleEdit(
                            scope=CollectionRuleScope(
                                kind="topic",
                                connection_id="factory",
                                topic_prefix="factory/machine",
                            ),
                            policy=CollectionPolicy(mode="sample", interval_seconds=1),
                            include_future_readings=True,
                        )
                    ],
                ),
                actor="integration@example.com",
            )
        await until(lambda: collection_applied(sessions, ingress))
        await publish(32)

        await until(
            lambda: voltage_recorded(sessions, snapshot, voltage_topic, accepted)
        )
        await policy(["voltage"], "off")
        await until(lambda: collection_applied(sessions, ingress))
        # Browser is closed; the selected collector remains active.
        before = await rows()
        for value in range(5):
            await publish(35 + value)
            await asyncio.sleep(0.3)
        assert await rows() > before
        await policy(["temperature"], "original")
        await until(lambda: collection_applied(sessions, ingress))
        before = await rows()
        # One persistent connection sends fresh observations as fast as QoS 1
        # acknowledgements allow, without artificial spacing that hides bursts.
        await publish_sequence(range(45, 53))
        await until(lambda: reached_rows(rows, before + 8))
        assert await rows() == before + 8
        saved = await policy(["temperature", "running"], "off")

        await until(lambda: collection_applied(sessions, ingress, idle=True))
        before = await rows()
        for _ in range(4):
            await publish(99)
            await asyncio.sleep(0.3)
        assert await rows() == before
        # Unselected fields sharing the same topic never become detector inputs.
        assert all(
            TopicMetadataExtractor().extract(topic).telemetry_type
            in {
                saved.runtime.bindings["temperature"]["telemetry_key"],
                saved.runtime.bindings["voltage"]["telemetry_key"],
            }
            for topic, _ in accepted
        )
    finally:
        await viewer.close()
        await ingress.stop()
        await collector.stop()
        client.disconnect()
        await asyncio.to_thread(client.loop_stop)


async def voltage_recorded(sessions, snapshot, voltage_topic, accepted):
    async with sessions() as session:
        state = await session.scalar(
            select(CollectionState).where(
                CollectionState.sensor_key
                == snapshot.runtime.bindings["voltage"]["telemetry_key"]
            )
        )
        return (
            state is not None
            and state.value == 230
            and any(topic == voltage_topic for topic, _ in accepted)
        )


async def has_rows(rows):
    return await rows() > 0


async def reached_rows(rows, expected):
    return await rows() >= expected


def readings(value):
    return json.dumps(
        {"temperature": value, "humidity": 50, "running": True, "voltage": 230}
    )


async def publish_sequence(values):
    # Paho advances this sequence on PUBACK and returns after every QoS 1
    # message is acknowledged, preserving upstream ordering on one socket.
    await asyncio.to_thread(
        multiple,
        [
            {"topic": "factory/machine/readings", "payload": readings(value), "qos": 1}
            for value in values
        ],
        hostname="127.0.0.1",
        port=28884,
    )
