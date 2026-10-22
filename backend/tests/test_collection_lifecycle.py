import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from off_key_core.db.collection_runtime import CollectionRuntimeSnapshot
from off_key_core.schemas.system import SystemDocument
from off_key_core.schemas.system_collection import SystemCollectionDefinition
from off_key_mqtt_proxy import proxy as proxy_module
from off_key_mqtt_proxy.config.config import MQTTSettings

from tests.support.collection import message
from tests.support.collection import runtime_catalog as catalog


@pytest.fixture
def proxy(monkeypatch):
    monkeypatch.setattr(proxy_module, "get_async_session_local", MagicMock())
    monkeypatch.setattr(
        proxy_module,
        "get_mqtt_settings",
        lambda: MQTTSettings(
            MQTT_USE_AUTH=False, MQTT_USE_TLS=False, ENVIRONMENT="development"
        ),
    )
    service = proxy_module.MQTTProxyService()
    service.session_factory = MagicMock(return_value=AsyncMock())
    service._save_status = AsyncMock()
    service.database_writer.drain = AsyncMock()
    service.mqtt_client = SimpleNamespace(
        is_connected=True,
        subscribe=AsyncMock(return_value=True),
        unsubscribe=AsyncMock(return_value=True),
        drain_publishes=AsyncMock(),
        subscription_manager=SimpleNamespace(
            generation=1,
            get_all_topics=lambda: set(),
            get_subscriptions=lambda: set(),
        ),
    )
    service.is_running = True
    service._task = MagicMock(done=lambda: False)
    return service


@pytest.mark.asyncio
async def test_new_policy_waits_for_database_and_publish_drain(proxy):
    snapshot = CollectionRuntimeSnapshot(
        revision=1, catalog=catalog(), ingress={}, collection={}
    )
    release = asyncio.Event()
    proxy.database_writer.drain = AsyncMock(side_effect=lambda *_: release.wait())

    async def drain(*_):
        await release.wait()

    proxy.database_writer.drain.side_effect = drain
    proxy.buffer.configure(snapshot.catalog, now=0)
    proxy.buffer.receive(message(snapshot.catalog, 1))
    task = asyncio.create_task(proxy._apply(snapshot))
    await asyncio.sleep(0)
    assert proxy.state["status"] == "applying"
    assert not proxy.get_readiness_status()["ready"]
    assert proxy.buffer.take(now=100) == []
    proxy.mqtt_client.subscribe.assert_not_awaited()
    release.set()
    await task
    assert proxy.state["status"] == "prepared"
    proxy.mqtt_client.drain_publishes.assert_awaited_once()
    assert not proxy.get_readiness_status()["ready"]


@pytest.mark.asyncio
async def test_denied_subscription_keeps_collection_closed_and_retry_can_prepare(proxy):
    snapshot = CollectionRuntimeSnapshot(
        revision=1, catalog=catalog(), ingress={}, collection={}
    )
    proxy.mqtt_client.subscribe.return_value = False
    with pytest.raises(RuntimeError, match="acknowledge"):
        await proxy._apply(snapshot)
    assert proxy._prepared_revision == -1
    proxy.buffer.receive(message(snapshot.catalog, 1))
    assert proxy.buffer.take(now=100) == []
    proxy.mqtt_client.subscribe.return_value = True
    await proxy._apply(snapshot)
    assert proxy._prepared_revision == 1


@pytest.mark.asyncio
async def test_activation_waits_for_matching_ingress_revision(proxy, monkeypatch):
    snapshot = CollectionRuntimeSnapshot(
        revision=2,
        catalog=catalog(),
        ingress={"revision": 1, "status": "applied"},
        collection={},
    )
    monkeypatch.setattr(
        proxy_module, "read_collection_runtime", AsyncMock(return_value=snapshot)
    )
    proxy.session_factory = MagicMock(return_value=AsyncMock())
    await proxy._refresh_configuration()
    assert proxy.revision == -1
    assert proxy.state["status"] == "prepared"
    snapshot.ingress["revision"] = 2
    await proxy._refresh_configuration()
    assert proxy.revision == 2
    assert proxy.get_readiness_status()["ready"]
    proxy.mqtt_client.is_connected = False
    assert not proxy.get_readiness_status()["ready"]


@pytest.mark.asyncio
async def test_label_revision_preserves_admission_samples_and_deadlines(
    proxy, monkeypatch
):
    snapshot = CollectionRuntimeSnapshot(
        revision=3,
        catalog=catalog(),
        ingress={"revision": 3, "status": "applied"},
        collection={},
    )
    read = AsyncMock(return_value=snapshot)
    monkeypatch.setattr(proxy_module, "read_collection_runtime", read)
    await proxy._refresh_configuration()
    proxy.buffer.configure(snapshot.catalog, now=0)
    proxy.buffer.receive(message(snapshot.catalog, 42))
    streams = proxy.buffer._streams
    deadlines = proxy.buffer._deadlines.copy()
    renamed = deepcopy(snapshot)
    renamed.revision = 4
    renamed.ingress["revision"] = 4
    source = renamed.catalog.sources[0]
    source.label = "Assembly broker"
    renamed.catalog.document.devices[0].label = "Assembly entity"
    renamed.catalog.document.streams[0].label = "Assembly temperature"
    read.return_value = renamed
    proxy._apply = AsyncMock(wraps=proxy._apply)
    proxy.database_writer.drain.reset_mock()
    proxy.mqtt_client.drain_publishes.reset_mock()
    proxy.mqtt_client.subscribe.reset_mock()
    proxy.mqtt_client.unsubscribe.reset_mock()
    await proxy._refresh_configuration()
    proxy._apply.assert_not_awaited()
    proxy.database_writer.drain.assert_not_awaited()
    proxy.mqtt_client.drain_publishes.assert_not_awaited()
    proxy.mqtt_client.subscribe.assert_not_awaited()
    proxy.mqtt_client.unsubscribe.assert_not_awaited()
    assert proxy.revision == proxy._prepared_revision == 4
    assert proxy.buffer._streams is streams and proxy.buffer._deadlines == deadlines
    assert proxy.state["status"] == "applied" and proxy.state["revision"] == 4
    assert proxy.buffer.take(now=9) == []
    assert proxy.buffer.take(now=10)[0].value == 42
    assert proxy.get_readiness_status()["ready"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["policy", "host", "topic", "generation"])
async def test_runtime_change_or_reconnect_still_reapplies_collection(
    proxy, monkeypatch, change
):
    snapshot = CollectionRuntimeSnapshot(
        revision=3,
        catalog=catalog(),
        ingress={"revision": 3, "status": "applied"},
        collection={},
    )
    read = AsyncMock(return_value=snapshot)
    monkeypatch.setattr(proxy_module, "read_collection_runtime", read)
    await proxy._refresh_configuration()
    changed = deepcopy(snapshot)
    changed.revision = 4
    changed.ingress["revision"] = 4
    source = changed.catalog.sources[0]
    source.label = "Renamed broker"
    if change == "policy":
        changed.catalog.document.streams[0].policy.mode = "original"
    elif change == "host":
        source.host = "changed.ts.net"
    elif change == "topic":
        changed.catalog.document.streams[0].topic = "telemetry/0/changed"
    else:
        proxy.mqtt_client.subscription_manager.generation += 1
    read.return_value = changed
    proxy._apply = AsyncMock(wraps=proxy._apply)
    await proxy._refresh_configuration()
    proxy._apply.assert_awaited_once_with(changed)
    assert proxy.revision == 4


@pytest.mark.asyncio
async def test_no_selection_is_healthy_idle(proxy, monkeypatch):
    snapshot = CollectionRuntimeSnapshot(
        revision=0,
        catalog=SystemCollectionDefinition(document=SystemDocument(), bindings={}),
        ingress={},
        collection={},
    )
    monkeypatch.setattr(
        proxy_module, "read_collection_runtime", AsyncMock(return_value=snapshot)
    )
    proxy.session_factory = MagicMock(return_value=AsyncMock())
    await proxy._refresh_configuration()
    assert proxy.get_readiness_status()["ready"] and proxy.state["idle"]
    proxy.mqtt_client.subscribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_all_off_catalogue_is_ready_without_an_ingress_worker(proxy, monkeypatch):
    snapshot = CollectionRuntimeSnapshot(
        revision=4, catalog=catalog("off"), collection={}, ingress={}
    )
    monkeypatch.setattr(
        proxy_module, "read_collection_runtime", AsyncMock(return_value=snapshot)
    )
    await proxy._refresh_configuration()
    assert proxy.revision == 4
    assert proxy.state["status"] == "applied" and proxy.state["idle"]
    assert proxy.get_readiness_status()["ready"]
    proxy.mqtt_client.subscribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_writer_ownership_loss_cancels_instead_of_draining(proxy):
    blocker = asyncio.Event()
    writer = proxy.database_writer
    writer._writer_task = asyncio.create_task(blocker.wait())
    writer._health_task = asyncio.create_task(blocker.wait())
    await writer.stop(drain=False)
    assert writer._writer_task.cancelled()
    assert writer._health_task.cancelled()


@pytest.mark.asyncio
async def test_state_commit_timestamp_advances_only_after_commit(proxy):
    configuration = catalog("original", "text")
    proxy.buffer.configure(configuration, now=0)
    proxy.buffer.receive(message(configuration, "ready"))
    await proxy._emit()
    committed_at = proxy.diagnostics.last_state_write_at
    assert committed_at is not None
    session = AsyncMock()
    session.commit.side_effect = RuntimeError("database unavailable")
    context = AsyncMock()
    context.__aenter__.return_value = session
    proxy.session_factory = MagicMock(return_value=context)
    proxy.buffer.configure(configuration, now=0)
    proxy.buffer.receive(message(configuration, "next"))
    with pytest.raises(RuntimeError, match="database unavailable"):
        await proxy._emit()
    assert proxy.diagnostics.last_state_write_at == committed_at
