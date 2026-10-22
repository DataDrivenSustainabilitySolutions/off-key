import asyncio
import json
from datetime import UTC, datetime

import pytest
from off_key_core.db.catalogue_v1_models import (
    AmbiboxCatalog,
)
from off_key_core.schemas.collection_wire import (
    decode_ingress_envelope,
    encode_ingress_envelope,
)
from off_key_mqtt_proxy.client.subscriptions import SubscriptionManager
from off_key_mqtt_proxy.collection_buffer import CollectionBuffer
from off_key_tactic_middleware.services.system_collection import SystemCollectionService
from pydantic import ValidationError

from tests.support.collection import catalog, message, runtime_catalog


def test_sampler_keeps_latest_new_observation_and_original_time_without_forward_fill():
    config = runtime_catalog()
    buffer = CollectionBuffer()
    buffer.configure(config, now=0)
    for value in range(1000):
        incoming = message(config, value)
        buffer.receive(incoming)
    assert buffer.metrics()["sample_slots"] == 1
    assert buffer.take(now=9) == []
    result = buffer.take(now=10)
    assert len(result) == 1 and result[0].value == 999
    assert result[0].received_at.timestamp() == incoming.payload["received_at"] / 1000
    assert buffer.take(now=20) == []


@pytest.mark.parametrize("retained,upstream", [(True, False), (False, True)])
def test_retained_values_are_snapshots(retained, upstream):
    config = runtime_catalog("original")
    buffer = CollectionBuffer()
    buffer.configure(config, now=0)
    buffer.receive(message(config, 12, retained=retained, upstream_retained=upstream))
    result = buffer.take(now=10)
    assert result[0].snapshot
    assert buffer.metrics()["original_queue"] == 0


def test_pause_and_unknown_topics_fail_closed_and_original_rate_is_bounded():
    config = runtime_catalog("original")
    buffer = CollectionBuffer(original_capacity=3)
    buffer.configure(config, now=0)
    for value in range(10):
        buffer.receive(message(config, value))
    assert buffer.metrics()["original_queue"] == 3
    assert buffer.metrics()["overload_dropped"] == 7
    buffer.pause()
    buffer.receive(message(config, 11))
    assert buffer.take(now=100) == []
    assert buffer.metrics()["unselected"] == 1


@pytest.mark.parametrize(
    "value", [True, float("nan"), float("inf"), {}, [], "bad", "x" * 5000]
)
def test_invalid_numeric_payloads_are_rejected(value):
    config = runtime_catalog("original")
    buffer = CollectionBuffer()
    buffer.configure(config, now=0)
    buffer.receive(message(config, value))
    assert buffer.take(now=100) == []
    assert buffer.metrics()["invalid"] == 1


@pytest.mark.parametrize(
    "envelope",
    [
        {"received_at": True},
        {"received_at": "1700000000000"},
        {"received_at": datetime(2100, 1, 1, tzinfo=UTC).timestamp() * 1000},
        {"upstream_retained": "false"},
        {"payload": 42},
        "not an envelope",
        {"missing": "payload"},
    ],
    ids=[
        "bool_time",
        "string_time",
        "future_time",
        "string_retained",
        "non_text_payload",
        "not_a_mapping",
        "missing_keys",
    ],
)
def test_malformed_ingress_envelopes_are_counted_invalid(envelope):
    config = runtime_catalog("original")
    buffer = CollectionBuffer()
    buffer.configure(config, now=0)
    incoming = message(config, 12)
    if isinstance(envelope, dict) and "missing" not in envelope:
        incoming.payload = {**incoming.payload, **envelope}
    else:
        incoming.payload = envelope
    buffer.receive(incoming)
    assert buffer.take(now=100) == []
    assert buffer.metrics()["invalid"] == 1


def test_ingress_envelopes_round_trip_in_milliseconds():
    received_at = datetime(2026, 10, 22, 12, 0, 0, 123456, UTC)
    millis = received_at.timestamp() * 1000
    encoded = encode_ingress_envelope("42", millis, True)
    assert list(json.loads(encoded)) == ["payload", "received_at", "upstream_retained"]
    assert decode_ingress_envelope(json.loads(encoded)) == ("42", received_at, True)


def test_state_is_coalesced_and_policy_changes_invalidate_monitor_inputs():
    config = runtime_catalog("original", "boolean")
    buffer = CollectionBuffer()
    buffer.configure(config, now=0)
    buffer.receive(message(config, True))
    buffer.receive(message(config, False))
    assert buffer.take(now=1)[0].value is False
    changed = config.model_copy(deep=True)
    changed.document.streams[0].policy.mode = "off"
    assert SystemCollectionService._changed_inputs(config, changed) == {
        config.streams()[0].accepted_topic
    }


def test_catalog_rejects_wildcards_duplicate_endpoints_and_invalid_local_binding():
    data = catalog().model_dump(mode="json")
    data["sources"][0]["chargers"][0]["sensors"][0]["upstream_topic"] = (
        "device/evCharger/+/#"
    )
    with pytest.raises(ValidationError):
        AmbiboxCatalog.model_validate(data)
    data = catalog().model_dump(mode="json")
    data["sources"].append(data["sources"][0])
    with pytest.raises(ValidationError):
        AmbiboxCatalog.model_validate(data)
    data = catalog().model_dump(mode="json")
    data["sources"][0]["chargers"][0]["local_id"] = "1"
    with pytest.raises(ValidationError):
        AmbiboxCatalog.model_validate(data)


@pytest.mark.asyncio
async def test_subscription_denial_and_reconnect_require_new_ack():
    class Client:
        def subscribe(self, topic, qos):
            return 0, 1

        def unsubscribe(self, topic):
            return 0, 2

    manager = SubscriptionManager()
    client = Client()
    manager.set_client(client)
    task = asyncio.create_task(manager.subscribe("ingress/test"))
    await asyncio.sleep(0)
    assert not task.done() and not manager.get_subscriptions()
    manager._on_subscribe(client, None, 1, [128])
    assert not await task
    task = asyncio.create_task(manager.subscribe("ingress/test"))
    await asyncio.sleep(0)
    manager._on_subscribe(client, None, 1, [0])
    assert await task
    replacement = Client()
    manager.set_client(replacement)
    assert not manager.get_subscriptions()
    assert manager.get_pending_subscriptions() == {"ingress/test"}
    task = asyncio.create_task(manager.unsubscribe("ingress/test"))
    await asyncio.sleep(0)
    manager._on_unsubscribe(replacement, None, 2)
    assert await task and not manager.get_all_topics()


@pytest.mark.asyncio
async def test_require_admin_does_not_trust_client_role():
    from fastapi import HTTPException
    from off_key_core.db.models import User
    from off_key_core.utils.enum import RoleEnum
    from off_key_tactic_middleware.api.collection_auth import require_admin

    with pytest.raises(HTTPException) as error:
        await require_admin(User(role=RoleEnum.user))
    assert error.value.status_code == 403
    admin = User(role=RoleEnum.admin)
    assert await require_admin(admin) is admin


@pytest.mark.parametrize("kind,value", [("text", "123"), ("identifier", "000123")])
def test_text_and_identifiers_preserve_numeric_looking_payloads(kind, value):
    config = runtime_catalog("original", kind)
    buffer = CollectionBuffer()
    buffer.configure(config, now=0)
    buffer.receive(message(config, value))
    assert buffer.take(now=1)[0].value == value


def test_retained_replay_cannot_replace_pending_live_sample():
    config = runtime_catalog()
    buffer = CollectionBuffer()
    buffer.configure(config, now=0)
    buffer.receive(message(config, 123))
    buffer.receive(message(config, 456, retained=True))
    observation = buffer.take(now=10)[0]
    assert observation.value == 123 and not observation.snapshot


@pytest.mark.parametrize("value", ['"\\u0000"', '"\\ud800"'])
def test_invalid_json_text_is_rejected_before_state_persistence(value):
    config = runtime_catalog("original", "text")
    buffer = CollectionBuffer()
    buffer.configure(config, now=0)
    buffer.receive(message(config, value))
    assert buffer.take(now=1) == []
    assert buffer.metrics()["invalid"] == 1
