"""Focused observation leases share only their selected upstream subscriptions."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from off_key_core.schemas.system import SystemConnection
from off_key_tactic_middleware.services.catalogue.system_live import LiveSessionError
from off_key_tactic_middleware.services.catalogue.system_live_mqtt import LiveMqttWorker

from tests.support.system_live import manager as harness
from tests.support.system_live import snapshot as configuration


@pytest.mark.asyncio
async def test_empty_view_does_not_open_any_upstream_broker():
    service, _ = harness()
    snapshot = configuration()
    lease = await service.acquire(snapshot, 1, snapshot.revision, [])
    assert service.workers == []
    assert service.snapshot(0)["streams"] == []
    await service.release(1, lease["lease_id"])


@pytest.mark.asyncio
async def test_selected_fields_share_one_topic_and_viewers_keep_independent_scopes():
    service, _ = harness()
    snapshot = configuration()
    snapshot.document.streams.append(
        snapshot.document.streams[0].model_copy(update={"id": "second"})
    )
    first, second = [stream.id for stream in snapshot.document.streams[:2]]
    lease_a = await service.acquire(snapshot, 1, snapshot.revision, [first])
    worker = service.workers[0]
    lease_b = await service.acquire(snapshot, 2, snapshot.revision, [second])
    assert service.workers == [worker]
    assert set(service.streams) == {first, second}
    await service.renew(snapshot, 1, lease_a["lease_id"], [])
    assert service.workers == [worker]
    assert set(service.streams) == {second}
    await service.release(2, lease_b["lease_id"])
    await service.reconcile(snapshot)
    assert worker.stopped and not service.workers
    await service.release(1, lease_a["lease_id"])


@pytest.mark.asyncio
async def test_switching_topic_updates_the_socket_and_releases_server_history():
    service, _ = harness()
    snapshot = configuration()
    first = snapshot.document.streams[0]
    second = first.model_copy(update={"id": "other", "topic": "room/other"})
    snapshot.document.streams.append(second)
    lease = await service.acquire(snapshot, 1, snapshot.revision, [first.id])
    worker = service.workers[0]
    worker.message(first.topic, b'{"temperature":20}', False)
    await service.renew(snapshot, 1, lease["lease_id"], [second.id])
    assert not worker.stopped
    assert service.workers == [worker]
    assert service.workers[0].topics == ["room/other"]
    assert all(item["stream_id"] == "other" for item in service.snapshot(0)["samples"])
    await service.renew(snapshot, 1, lease["lease_id"], [first.id])
    assert service.workers == [worker]
    assert worker.topics == [first.topic]
    await service.stop()


@pytest.mark.asyncio
async def test_leaving_a_blocked_broker_cleans_its_status_before_switching():
    service, _ = harness()
    snapshot = configuration(host="blocked")
    first = snapshot.document.streams[0]
    snapshot.document.connections.append(
        SystemConnection(id="reachable", label="Reachable", host="broker")
    )
    second = first.model_copy(update={"id": "other", "connection_id": "reachable"})
    snapshot.document.streams.append(second)
    lease = await service.acquire(snapshot, 1, snapshot.revision, [first.id])
    assert service.snapshot(0)["connections"][0]["state"] == "blocked"
    await service.renew(snapshot, 1, lease["lease_id"], [second.id])
    result = service.snapshot(0)
    assert len(result["connections"]) == 1
    assert result["connections"][0]["state"] == "connected"
    await service.stop()


@pytest.mark.asyncio
async def test_scope_replacement_counts_other_viewers_but_not_the_old_scope():
    service, _ = harness()
    service.settings.SYSTEM_LIVE_MAX_STREAMS = 1
    snapshot = configuration()
    first = snapshot.document.streams[0]
    second = first.model_copy(update={"id": "other", "topic": "room/other"})
    snapshot.document.streams.append(second)
    lease = await service.acquire(snapshot, 1, snapshot.revision, [first.id])
    await service.renew(snapshot, 1, lease["lease_id"], [second.id])
    assert set(service.streams) == {second.id}
    with pytest.raises(LiveSessionError, match="stream limit"):
        await service.acquire(snapshot, 2, snapshot.revision, [first.id])
    await service.stop()


def test_mqtt_scope_updates_keep_the_socket_and_resubscribe_to_current_topics():
    client = MagicMock()
    client.subscribe.side_effect = [(0, 1), (0, 2), (0, 3)]
    client.unsubscribe.return_value = (0, 4)
    state = MagicMock()
    worker = LiveMqttWorker(
        SystemConnection(id="broker", label="Broker", host="broker"),
        ["room/values"],
        None,
        MagicMock(),
        state,
        client_factory=lambda *_args, **_kwargs: client,
    )
    good = SimpleNamespace(is_failure=False)
    worker.start()
    worker._connected(client, None, None, good, None)
    worker._subscribed(client, None, 1, [good], None)
    state.reset_mock()
    assert worker.update_topics(["room/other"])
    client.subscribe.assert_called_with([("room/other", 0)])
    client.unsubscribe.assert_called_once_with(["room/values"])
    client.disconnect.assert_not_called()
    assert client.connect_async.call_count == 1
    state.assert_not_called()
    worker._subscribed(client, None, 2, [good], None)
    state.assert_called_once_with("connected", None)
    worker._disconnected(client, None, None, good, None)
    worker._connected(client, None, None, good, None)
    client.subscribe.assert_called_with([("room/other", 0)])
    worker.stop()


def test_failed_scope_update_does_not_claim_a_connected_subscription():
    client = MagicMock()
    client.subscribe.side_effect = [(0, 1), (4, None)]
    state = MagicMock()
    worker = LiveMqttWorker(
        SystemConnection(id="broker", label="Broker", host="broker"),
        ["room/values"],
        None,
        MagicMock(),
        state,
        client_factory=lambda *_args, **_kwargs: client,
    )
    good = SimpleNamespace(is_failure=False)
    worker._connected(client, None, None, good, None)
    worker._subscribed(client, None, 1, [good], None)
    state.reset_mock()
    assert not worker.update_topics(["room/other"])
    assert worker.denied
    client.disconnect.assert_called_once()
    worker._subscribed(client, None, 1, [good], None)
    assert all(call.args[0] != "connected" for call in state.call_args_list)
    worker.stop()


def test_refused_credentials_stop_the_worker_instead_of_resending_them():
    client = MagicMock()
    state = MagicMock()
    worker = LiveMqttWorker(
        SystemConnection(id="broker", label="Broker", host="broker"),
        ["room/values"],
        None,
        MagicMock(),
        state,
        client_factory=lambda *_args, **_kwargs: client,
    )
    worker.start()
    worker._connected(client, None, None, SimpleNamespace(is_failure=True), None)
    assert worker.denied
    client.disconnect.assert_called_once()
    worker._disconnected(client, None, None, SimpleNamespace(is_failure=True), None)
    state.assert_called_once_with(
        "error", "The broker rejected the connection credentials."
    )
    assert not worker.update_topics(["room/other"])
    client.subscribe.assert_not_called()
    worker.stop()
