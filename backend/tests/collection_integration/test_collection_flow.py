"""Run with OFFKEY_COLLECTION_INTEGRATION=1 after compose up in this directory."""

import asyncio
import os
from contextlib import suppress
from urllib.parse import quote

import pytest
import pytest_asyncio
from off_key_core.db.base import Base
from off_key_core.db.collection import read_collection_configuration
from off_key_core.db.models import Charger, CollectionState, Telemetry
from off_key_core.db.schema import bootstrap_schema
from off_key_core.schemas.collection import (
    AmbiboxCatalog,
    CatalogChange,
    CollectionPolicy,
)
from off_key_mqtt_proxy import proxy as proxy_module
from off_key_mqtt_proxy.config.config import MQTTSettings
from off_key_tactic_middleware.api.v1.collection import read_sensor_activity
from off_key_tactic_middleware.config.collection import AmbiboxSettings
from off_key_tactic_middleware.services import ambibox_ingress as ingress_module
from off_key_tactic_middleware.services import collection as collection_module
from paho.mqtt.publish import multiple, single
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.skipif(
    os.getenv("OFFKEY_COLLECTION_INTEGRATION") != "1",
    reason="Requires the isolated MQTT collection compose fixture",
)


async def until(check):
    async with asyncio.timeout(30):
        # External brokers and DB state have no local event to await.
        while not await check():  # noqa: ASYNC110
            await asyncio.sleep(0.1)


@pytest_asyncio.fixture
async def database(monkeypatch):
    # Fixed local fixture DSN: this test never uses application credentials or DB URLs.
    engine = create_async_engine(
        "postgresql+asyncpg://collection_test:collection-test-password@127.0.0.1:25432/collection_test"
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(collection_module, "get_async_session_local", lambda: sessions)
    async with engine.begin() as connection:
        await connection.run_sync(bootstrap_schema)
        await connection.execute(
            text("TRUNCATE " + ", ".join(Base.metadata.tables) + " CASCADE")
        )
    try:
        yield engine, sessions
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_broker_isolation_sampling_pause_reconnect_and_idle(
    monkeypatch, database
):
    engine, sessions = database
    settings = AmbiboxSettings(
        AMBIBOX_INGRESS_ENABLED=True,
        AMBIBOX_ALLOWED_HOSTS=["charger-a", "charger-b"],
        AMBIBOX_EMQX_API_URL="http://127.0.0.1:28083/api/v5",
        AMBIBOX_EMQX_API_KEY="collection-test",
        AMBIBOX_EMQX_API_SECRET="test-emqx-secret",
        AMBIBOX_GOST_API_URL="http://127.0.0.1:28080",
        AMBIBOX_GOST_USERNAME="offkey",
        AMBIBOX_GOST_PASSWORD="test-gost-password",
        AMBIBOX_FORWARD_HOST="forwarder",
        AMBIBOX_SOCKS_SERVER="socks:1055",
    )
    for module in (proxy_module, ingress_module):
        monkeypatch.setattr(module, "get_async_engine", lambda: engine)
        monkeypatch.setattr(module, "get_async_session_local", lambda: sessions)
    monkeypatch.setattr(collection_module, "get_ambibox_settings", lambda: settings)
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
    config = AmbiboxCatalog.model_validate(
        {
            "default_policy": {"mode": "sample", "interval_seconds": 1},
            "sources": [
                {
                    "label": name,
                    "host": name,
                    "chargers": [
                        {
                            "label": name,
                            "policy": None,
                            "sensors": [
                                {
                                    "key": "temperature",
                                    "label": "Temperature",
                                    "upstream_topic": "device/evCharger/0/temperature",
                                },
                                {
                                    "key": "power",
                                    "label": "Power",
                                    "upstream_topic": "device/evCharger/0/power",
                                    "policy": {"mode": "off"},
                                },
                                {
                                    "key": "version",
                                    "label": "Version",
                                    "upstream_topic": "device/evCharger/0/version",
                                    "value_type": "text",
                                },
                            ],
                        }
                    ],
                }
                for name in ("charger-a", "charger-b")
            ],
        }
    )

    async def save(catalog, revision):
        async with sessions() as session:
            result = await collection_module.CollectionService(session).apply(
                CatalogChange(expected_revision=revision, catalog=catalog),
                actor="integration@test.invalid",
            )
            await session.commit()
            return result

    snapshot = await save(config, 0)
    config = snapshot.catalog
    for port in (28884, 28885):
        await asyncio.to_thread(
            single,
            "device/evCharger/0/temperature",
            "777",
            hostname="127.0.0.1",
            port=port,
            retain=True,
        )
        await asyncio.to_thread(
            single,
            "device/evCharger/0/version",
            "v1.2",
            hostname="127.0.0.1",
            port=port,
            retain=True,
        )
    proxy = proxy_module.MQTTProxyService()
    ingress = ingress_module.AmbiboxIngress(settings)

    async def applied(revision):
        async with sessions() as session:
            saved = await read_collection_configuration(session)
            return (
                saved.collection.get("revision") == revision
                and saved.collection.get("status") == "applied"
                and saved.ingress.get("revision") == revision
                and saved.ingress.get("status") == "applied"
            )

    async def count():
        async with sessions() as session:
            return await session.scalar(select(func.count()).select_from(Telemetry))

    try:
        await proxy.start()
        await ingress.start()
        await until(lambda: applied(1))
        await asyncio.sleep(1.5)
        assert await count() == 0, "Retained values must not create fresh history"
        async with sessions() as session:
            states = list(await session.scalars(select(CollectionState)))
            assert len(states) == 4 and all(row.is_snapshot for row in states)
            activity = await read_sensor_activity(session, 1, proxy.state)
            assert set(activity) == {row.charger_id for row in states}
            assert all(
                observation.is_snapshot
                for sensors in activity.values()
                for observation in sensors.values()
            )
            assert not any(await session.scalars(select(Charger.online)))
        # A live state value establishes contact without creating numeric history.
        await asyncio.to_thread(
            single,
            "device/evCharger/0/version",
            "v1.3",
            hostname="127.0.0.1",
            port=28884,
        )

        async def first_online():
            async with sessions() as session:
                return await session.scalar(
                    select(Charger.online).where(
                        Charger.charger_id == str(config.sources[0].chargers[0].id)
                    )
                )

        await until(first_online)
        assert await count() == 0
        for port, offset in ((28884, 0), (28885, 100)):
            messages = [
                {
                    "topic": "device/evCharger/0/temperature",
                    "payload": str(offset + number),
                }
                for number in range(100)
            ]
            messages += [{"topic": "device/evCharger/0/power", "payload": "999"}]
            await asyncio.to_thread(multiple, messages, hostname="127.0.0.1", port=port)

        async def latest_samples_arrived():
            async with sessions() as session:
                values = {
                    row.charger_id: row.value
                    for row in await session.scalars(
                        select(Telemetry).order_by(Telemetry.timestamp)
                    )
                }
                return set(values.values()) == {99, 199}

        await until(latest_samples_arrived)
        async with sessions() as session:
            rows = list(await session.scalars(select(Telemetry)))
            assert all(await session.scalars(select(Charger.online)))
            activity = await read_sensor_activity(session, 1, proxy.state)
            assert set(activity) == {row.charger_id for row in rows}
            assert all(
                not sensors["temperature"].is_snapshot for sensors in activity.values()
            )
        assert {row.charger_id for row in rows} == {
            str(source.chargers[0].id) for source in config.sources
        }
        assert {row.type for row in rows} == {"temperature"}
        # A burst can cross a sampling boundary. Intermediate window samples are
        # valid; the last values must arrive and the burst must be downsampled.
        assert len(rows) < 200
        history_count = len(rows)
        # Changing a concrete binding must purge the previous local snapshot while
        # the connector is disabled, before collection resumes on the new topic.
        sensor = config.sources[0].chargers[0].sensors[0]
        sensor.upstream_topic = "device/evCharger/0/replacement"
        await save(config, 1)
        await until(lambda: applied(2))
        await asyncio.sleep(1)
        async with sessions() as session:
            assert (
                await session.scalar(
                    select(CollectionState).where(
                        CollectionState.charger_id
                        == str(config.sources[0].chargers[0].id),
                        CollectionState.sensor_key == "temperature",
                    )
                )
                is None
            )
        sensor.upstream_topic = "device/evCharger/0/temperature"
        await save(config, 2)
        await until(lambda: applied(3))
        # Same policy is restored on reconnect; local retained cache stays a snapshot.
        await proxy.mqtt_client.disconnect()
        proxy.mqtt_client.set_message_handler(proxy.buffer.receive)
        await until(lambda: applied(3))
        await asyncio.sleep(3)
        assert await count() == history_count
        config.sources[0].chargers[0].policy = CollectionPolicy(mode="off")
        await save(config, 3)
        await until(lambda: applied(4))
        baseline = await count()
        await asyncio.to_thread(
            single,
            "device/evCharger/0/temperature",
            "1234",
            hostname="127.0.0.1",
            port=28884,
        )
        await asyncio.sleep(1.5)
        assert await count() == baseline
        source = config.sources[0]
        state = await ingress.emqx.request(
            "GET", f"connectors/mqtt:offkey_ambibox_{source.id.hex}"
        )
        assert state["enable"] is False
        config.sources[1].chargers[0].policy = config.sources[0].chargers[0].policy
        await save(config, 4)
        await until(lambda: applied(5))
        assert proxy.get_readiness_status()["ready"]
        assert proxy.state["idle"]
        assert not proxy.mqtt_client.subscription_manager.get_subscriptions()
        # Removing a source must also work when its retained cache is already empty.
        for source in config.sources:
            await ingress.emqx.request(
                "DELETE",
                "mqtt/retainer/message/"
                + quote(f"ingress/ambibox/{source.id}/#", safe=""),
            )
        await save(AmbiboxCatalog(), 5)
        await until(lambda: applied(6))
        assert await ingress._list_emqx("rules") == []
        assert await ingress._list_emqx("connectors") == []
    finally:
        await ingress.stop()
        with suppress(Exception):
            await proxy.stop()


@pytest.mark.asyncio
async def test_catalog_api_authorization_revisions_and_monitor_pause(
    monkeypatch, database
):
    from datetime import UTC, datetime, timedelta
    from unittest.mock import AsyncMock, MagicMock

    import httpx
    from backend.tests.test_collection import catalog
    from backend.tests.test_gateway_auth_token_types import _set_auth_env
    from fastapi import FastAPI
    from jose import jwt
    from off_key_core.config.auth import get_auth_settings
    from off_key_core.db.base import get_db_async
    from off_key_core.db.models import MonitoringService, User
    from off_key_core.utils.enum import RoleEnum
    from off_key_tactic_middleware.api.v1.collection import router

    _, sessions = database
    _set_auth_env(monkeypatch)
    settings = get_auth_settings()
    async with sessions() as session:
        session.add_all(
            [
                User(
                    id=1,
                    email="admin@example.com",
                    hashed_password="unused",
                    is_verified=True,
                    role=RoleEnum.admin,
                ),
                User(
                    id=2,
                    email="reader@example.com",
                    hashed_password="unused",
                    is_verified=True,
                    role=RoleEnum.user,
                ),
            ]
        )
        await session.commit()

    async def session_dependency():
        async with sessions() as session, session.begin():
            yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db_async] = session_dependency

    def headers(user_id, email):
        token = jwt.encode(
            {
                "user_id": user_id,
                "sub": email,
                "role": "admin",
                "session_version": 0,
                "iss": settings.JWT_ISSUER,
                "aud": settings.JWT_AUDIENCE,
                "exp": datetime.now(UTC) + timedelta(minutes=5),
            },
            settings.JWT_SECRET.get_secret_value(),
            algorithm="HS256",
        )
        return {"Authorization": f"Bearer {token}"}

    admin = headers(1, "admin@example.com")
    reader = headers(2, "reader@example.com")
    configuration = catalog()
    change = {"expected_revision": 0, "catalog": configuration.model_dump(mode="json")}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        assert (await client.get("/collection")).status_code == 401
        visible = await client.get("/collection", headers=reader)
        assert visible.status_code == 200 and not visible.json()["can_edit"]
        assert (
            await client.put("/collection", headers=reader, json=change)
        ).status_code == 403
        # Both writes read revision 0; only one may commit its replacement.
        first, second = await asyncio.gather(
            *[client.put("/collection", headers=admin, json=change) for _ in range(2)]
        )
        assert sorted([first.status_code, second.status_code]) == [200, 409]
        saved = await client.get("/collection", headers=admin)
        assert saved.json()["revision"] == 1
        assert saved.json()["can_edit"]
        template = await client.get("/collection/ambibox-template", headers=reader)
        assert template.status_code == 200
        inventory = AmbiboxCatalog.model_validate(template.json())
        assert sum(source.verified for source in inventory.sources) == 4
        assert not inventory.streams(selected_only=True)

        async with sessions() as session:
            session.add(
                MonitoringService(
                    id="monitor-test",
                    container_id="fixture-workload",
                    container_name="Temperature",
                    mqtt_topic=[configuration.streams()[0].accepted_topic],
                    status=True,
                )
            )
            await session.commit()
        configuration.sources[0].chargers[0].policy = CollectionPolicy(mode="off")
        change = {
            "expected_revision": 1,
            "catalog": configuration.model_dump(mode="json"),
        }
        preview = await client.post("/collection/preview", headers=admin, json=change)
        assert preview.status_code == 200
        assert preview.json()["affected_monitors"] == [
            {"id": "monitor-test", "name": "Temperature"}
        ]
        assert (
            await client.put("/collection", headers=admin, json=change)
        ).status_code == 409
        remove = AsyncMock()
        monkeypatch.setattr(collection_module, "get_async_docker", MagicMock())
        monkeypatch.setattr(collection_module.RadarWorkloadManager, "remove", remove)
        changed = await client.put(
            "/collection",
            headers=admin,
            json={
                **change,
                "pause_affected_monitors": True,
            },
        )
        assert changed.status_code == 200 and changed.json()["revision"] == 2
        remove.assert_awaited_once_with("fixture-workload")
        async with sessions() as session:
            monitor = await session.get(MonitoringService, "monitor-test")
            assert not monitor.status and monitor.operational_stage == "stopped"
        history = await client.get("/collection/revisions", headers=reader)
        assert [row["revision"] for row in history.json()] == [2, 1]


@pytest.mark.asyncio
async def test_sustained_traffic_stays_bounded_during_write_outage_and_recovers(
    monkeypatch, database
):
    """Block real telemetry INSERTs while MQTT continues delivering observations."""
    import json
    import time
    from datetime import UTC, datetime

    from backend.tests.test_collection import catalog
    from off_key_core.db.models import CollectionConfiguration
    from sqlalchemy import update

    engine, sessions = database
    configuration = catalog("original")
    sensors = configuration.sources[0].chargers[0].sensors
    sensors.append(
        sensors[0].model_copy(
            update={
                "key": "sampled_temperature",
                "upstream_topic": "device/evCharger/0/sampled_temperature",
                "policy": CollectionPolicy(mode="sample", interval_seconds=1),
            }
        )
    )
    monkeypatch.setattr(proxy_module, "get_async_engine", lambda: engine)
    monkeypatch.setattr(proxy_module, "get_async_session_local", lambda: sessions)
    monkeypatch.setattr(
        proxy_module,
        "get_mqtt_settings",
        lambda: MQTTSettings(
            MQTT_BROKER_HOST="127.0.0.1",
            MQTT_BROKER_PORT=28883,
            MQTT_USE_AUTH=False,
            MQTT_USE_TLS=False,
            ENVIRONMENT="development",
            MQTT_BATCH_SIZE=8,
            MQTT_BATCH_TIMEOUT=0.1,
            MQTT_MAX_MESSAGE_QUEUE_SIZE=100,
            MQTT_CONNECTION_TIMEOUT=5,
        ),
    )
    async with sessions() as session:
        snapshot = await collection_module.CollectionService(session).apply(
            CatalogChange(expected_revision=0, catalog=configuration),
            actor="outage@test.invalid",
        )
        # This test targets application admission/writes. The separate two-broker
        # test above exercises the actual controller and source routing.
        await session.execute(
            update(CollectionConfiguration).values(
                ingress_status={"revision": snapshot.revision, "status": "applied"}
            )
        )
        await session.commit()
    streams = snapshot.catalog.streams()
    proxy = proxy_module.MQTTProxyService()
    stop_publishing = asyncio.Event()
    publisher = None

    async def ready():
        assert proxy._task is not None and not proxy._task.done(), proxy.state
        return proxy.get_readiness_status()["ready"]

    async def publish(values):
        millis = int(datetime.now(UTC).timestamp() * 1000)
        await asyncio.to_thread(
            multiple,
            [
                {
                    "topic": stream.ingress_topic,
                    "qos": 1,
                    "payload": json.dumps(
                        {
                            "payload": value,
                            "received_at": millis + index,
                            "upstream_retained": False,
                        }
                    ),
                }
                for index, value in enumerate(values)
                for stream in streams
            ],
            hostname="127.0.0.1",
            port=28883,
        )

    async def flood():
        while not stop_publishing.is_set():
            await publish(range(64))

    async def written(value):
        async with sessions() as session:
            types = set(
                await session.scalars(
                    select(Telemetry.type).where(Telemetry.value == value)
                )
            )
            return types == {stream.sensor.key for stream in streams}

    async def saturated():
        return proxy.buffer.metrics().get("overload_dropped", 0) > 0

    try:
        await proxy.start()
        await until(ready)
        await publish([12345])
        await until(lambda: written(12345))
        baseline = proxy.database_writer.total_records_written
        async with engine.connect() as outage:
            transaction = await outage.begin()
            try:
                await outage.execute(
                    text("LOCK TABLE telemetry IN ACCESS EXCLUSIVE MODE")
                )
                publisher = asyncio.create_task(flood())
                await until(saturated)
                received_before = proxy.buffer.metrics()["received"]
                coalesced_before = proxy.buffer.metrics().get("coalesced", 0)
                populated_slots = 0
                task_count = len(asyncio.all_tasks())
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    buffer = proxy.buffer.metrics()
                    writer = proxy.database_writer
                    assert buffer["original_queue"] <= 100
                    assert buffer["sample_slots"] <= 1
                    populated_slots = max(populated_slots, buffer["sample_slots"])
                    assert writer.pending_batch.size() <= 8
                    assert (
                        sum(
                            batch.size() for batch in writer.processing_batches.values()
                        )
                        <= 8
                    )
                    assert len(asyncio.all_tasks()) <= task_count + 5
                    assert not publisher.done()
                    await asyncio.sleep(0.05)
                assert proxy.buffer.metrics()["received"] > received_before + 100
                assert proxy.buffer.metrics()["coalesced"] > coalesced_before + 100
                assert populated_slots == 1
                assert proxy.database_writer.total_records_written == baseline
            finally:
                await transaction.rollback()
        stop_publishing.set()
        await asyncio.wait_for(publisher, timeout=10)
        await proxy.database_writer.drain()

        async def drained():
            return proxy.buffer.metrics()["original_queue"] == 0

        await until(drained)
        await publish([999999])
        await until(lambda: written(999999))
        assert proxy.buffer.metrics()["overload_dropped"] > 0
        assert proxy.get_readiness_status()["ready"]
    finally:
        stop_publishing.set()
        if publisher is not None:
            with suppress(Exception, asyncio.CancelledError):
                await asyncio.wait_for(publisher, timeout=10)
        await proxy.stop()
