import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.error import HTTPError
from urllib.parse import quote

import pytest
from off_key_core.schemas.collection import CatalogSnapshot
from off_key_mqtt_proxy import proxy as proxy_module
from off_key_mqtt_proxy.config.config import MQTTSettings
from off_key_tactic_middleware.config.collection import AmbiboxSettings
from off_key_tactic_middleware.services import ambibox_ingress as ingress_module
from off_key_tactic_middleware.services.ambibox_ingress import (
    AmbiboxIngress,
    IngressError,
    configuration_matches,
    source_resources,
)

from .test_collection import catalog, message


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
    snapshot = CatalogSnapshot(revision=1, catalog=catalog())
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
    snapshot = CatalogSnapshot(revision=1, catalog=catalog())
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
    snapshot = CatalogSnapshot(
        revision=2, catalog=catalog(), ingress={"revision": 1, "status": "applied"}
    )
    monkeypatch.setattr(
        proxy_module, "read_collection_configuration", AsyncMock(return_value=snapshot)
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
async def test_no_selection_is_healthy_idle(proxy, monkeypatch):
    snapshot = CatalogSnapshot(revision=0, catalog={})
    monkeypatch.setattr(
        proxy_module, "read_collection_configuration", AsyncMock(return_value=snapshot)
    )
    proxy.session_factory = MagicMock(return_value=AsyncMock())
    await proxy._refresh_configuration()
    assert proxy.get_readiness_status()["ready"] and proxy.state["idle"]
    proxy.mqtt_client.subscribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_management_error_does_not_claim_resource_success():
    worker = AmbiboxIngress()
    worker.emqx.request = AsyncMock(side_effect=IngressError("unavailable"))
    with pytest.raises(IngressError):
        await worker._upsert_emqx(
            "sources", "mqtt:test", {"type": "mqtt", "name": "test"}
        )


@pytest.mark.asyncio
async def test_upsert_creates_updates_without_identity_and_ignores_masked_password():
    worker = AmbiboxIngress()
    desired = {"type": "mqtt", "name": "test", "enable": True, "password": "secret"}
    actual = {**desired, "password": "******"}
    assert configuration_matches(desired, actual)
    worker.emqx.request = AsyncMock(side_effect=[None, {}, actual])
    assert await worker._upsert_emqx("connectors", "mqtt:test", desired) == actual
    assert worker.emqx.request.await_args_list[1].args == (
        "POST",
        "connectors",
        desired,
    )
    worker.emqx.request = AsyncMock(
        side_effect=[{**actual, "enable": False}, {}, actual]
    )
    await worker._upsert_emqx("connectors", "mqtt:test", desired)
    body = worker.emqx.request.await_args_list[1].args[2]
    assert "type" not in body and "name" not in body and body["enable"]


def test_rule_matching_rejects_extra_actions():
    assert not configuration_matches({"actions": [1]}, {"actions": [1, 2]})


@pytest.mark.asyncio
async def test_masked_credentials_can_be_reapplied_after_secret_rotation():
    worker = AmbiboxIngress()
    actual = {"type": "mqtt", "name": "test", "password": "******"}
    desired = {**actual, "password": "rotated-secret"}
    worker.emqx.request = AsyncMock(side_effect=[{}, actual])
    await worker._upsert_emqx(
        "connectors", "mqtt:test", desired, current=actual, force=True
    )
    assert worker.emqx.request.await_args_list[0].args == (
        "PUT",
        "connectors/mqtt%3Atest",
        {"password": "rotated-secret"},
    )


@pytest.mark.asyncio
async def test_writer_ownership_loss_cancels_instead_of_draining(proxy):
    blocker = asyncio.Event()
    writer = proxy.database_writer
    writer._writer_task = asyncio.create_task(blocker.wait())
    writer._health_task = asyncio.create_task(blocker.wait())
    await writer.stop(drain=False)
    assert writer._writer_task.cancelled()
    assert writer._health_task.cancelled()


@pytest.fixture
def configured_ingress():
    configuration = catalog()
    source = configuration.sources[0]
    source.forward_port = 20000
    worker = AmbiboxIngress(AmbiboxSettings(AMBIBOX_MQTT_PASSWORD="rotated-password"))
    route, connector, mqtt_source, rule = source_resources(
        source, configuration, worker.settings
    )
    name = connector["name"]
    connector_path = "connectors/" + quote("mqtt:" + name, safe="")
    resources = {
        connector_path: {
            **connector,
            "password": "old-password",
            "status": "connected",
        },
        "sources/" + quote("mqtt:" + name, safe=""): {
            **mqtt_source,
            "status": "connected",
        },
        "rules/" + name: rule,
    }
    cache = {"retained": True, "purge_attempts": 0, "fail_purge": False}

    async def request(method, path, payload=None):
        if method == "GET":
            collection = path.split("?", 1)[0]
            if collection in {"rules", "sources", "connectors"}:
                entries = [
                    deepcopy(value)
                    for key, value in resources.items()
                    if key.startswith(collection + "/")
                ]
                return (
                    {"data": entries, "meta": {"hasnext": False}}
                    if collection == "rules"
                    else entries
                )
            result = deepcopy(resources.get(path))
            if result and "password" in result:
                result["password"] = "******"
            return result
        if method == "PUT" and path.endswith("/enable/false"):
            resources[path.removesuffix("/enable/false")]["enable"] = False
        elif method == "PUT":
            resources[path].update(deepcopy(payload))
        elif method == "DELETE" and path.startswith("mqtt/retainer/"):
            cache["purge_attempts"] += 1
            if cache["fail_purge"]:
                cache["fail_purge"] = False
                raise IngressError("temporary purge failure")
            cache["retained"] = False
        elif method == "DELETE":
            del resources[path]
        else:
            raise AssertionError((method, path))
        return None

    worker.emqx.request = AsyncMock(side_effect=request)
    worker.gost.request = AsyncMock()
    return (
        worker,
        configuration,
        {"services": [route]},
        resources,
        cache,
        connector_path,
    )


@pytest.mark.asyncio
async def test_source_reconciliation_applies_masked_credentials_once(
    configured_ingress,
):
    worker, configuration, gost, resources, _, connector_path = configured_ingress
    source = configuration.sources[0]
    assert (await worker._reconcile_source(source, configuration, gost))["configured"]
    assert resources[connector_path]["password"] == "rotated-password"
    worker.emqx.request.reset_mock()
    assert (await worker._reconcile_source(source, configuration, gost))["configured"]
    assert not any(
        call.args[0] == "PUT" for call in worker.emqx.request.await_args_list
    )


@pytest.mark.parametrize("change", ["binding", "topic"])
@pytest.mark.asyncio
async def test_failed_purge_preserves_remap_marker_until_retry(
    configured_ingress, change
):
    worker, configuration, gost, resources, cache, connector_path = configured_ingress
    source = configuration.sources[0]
    old_description = resources[connector_path]["description"]
    rule_path = "rules/" + resources[connector_path]["name"]
    old_sql = resources[rule_path]["sql"]
    if change == "binding":
        source.host = "replacement.ts.net"
    else:
        source.chargers[0].sensors[0].upstream_topic = "device/evCharger/0/replacement"
    cache["fail_purge"] = True
    assert not (await worker._reconcile_source(source, configuration, gost))[
        "configured"
    ]
    assert resources[connector_path]["enable"] is False
    assert resources[connector_path]["description"] == old_description
    assert resources[rule_path]["sql"] == old_sql
    assert cache["retained"]
    assert (await worker._reconcile_source(source, configuration, gost))["configured"]
    assert cache["purge_attempts"] == 2 and not cache["retained"]
    assert resources[connector_path]["enable"] is True


@pytest.mark.asyncio
async def test_obsolete_rule_survives_failed_purge_for_retry(configured_ingress):
    worker, _, gost, resources, cache, connector_path = configured_ingress
    cache["fail_purge"] = True
    with pytest.raises(IngressError, match="purge"):
        await worker._remove_obsolete(set(), gost)
    assert any(path.startswith("rules/") for path in resources)
    assert resources[connector_path]["enable"] is False
    await worker._remove_obsolete(set(), gost)
    assert cache["purge_attempts"] == 2 and not cache["retained"]
    assert not resources


@pytest.mark.parametrize("status", [404, 403, 500])
@pytest.mark.asyncio
async def test_retained_cleanup_accepts_absence_but_not_management_failures(
    monkeypatch, status
):
    monkeypatch.setattr(
        ingress_module,
        "urlopen",
        MagicMock(side_effect=HTTPError("http://broker", status, "error", {}, None)),
    )
    worker = AmbiboxIngress()
    if status == 404:
        assert (
            await worker.emqx.request("DELETE", "mqtt/retainer/message/topic") is None
        )
    else:
        with pytest.raises(IngressError, match=f"HTTP {status}"):
            await worker.emqx.request("DELETE", "mqtt/retainer/message/topic")
