"""Public-API fixtures for the explicitly enabled, disposable stack tests."""

import time
from dataclasses import dataclass
from uuid import uuid4

import httpx
import pytest


@dataclass(frozen=True)
class RecordedEntity:
    broker_id: str
    device_id: str
    reading_ids: tuple[str, ...]
    entity_id: str
    keys: dict[str, str]
    topics: dict[str, str]
    accepted_topics: tuple[str, ...]


def add_recorded_entity(
    client: httpx.Client, *, label: str, keys: tuple[str, ...]
) -> RecordedEntity:
    """Importing structure stays Off; a second action opts these inputs in."""
    identity = uuid4().hex
    broker_id, device_id = f"test-broker-{identity}", f"test-entity-{identity}"
    reading_ids = tuple(f"test-reading-{identity}-{key}" for key in keys)
    topics = {key: f"tests/{identity}/{key}" for key in keys}
    response = client.get("/v1/catalogue")
    response.raise_for_status()
    current = response.json()
    document = current["document"]
    document["brokers"].append(
        {
            "id": broker_id,
            "label": "Test broker",
            "host": "source-broker",
            "protocol": "mqtt",
            "port": 1883,
            "tls": False,
            "transport": "tcp",
        }
    )
    document["devices"].append(
        {
            "id": device_id,
            "label": label,
            "broker_id": broker_id,
            "kind": "entity",
        }
    )
    for key, reading_id in zip(keys, reading_ids, strict=True):
        document["readings"].append(
            {
                "id": reading_id,
                "label": key,
                "broker_id": broker_id,
                "device_id": device_id,
                "topic": topics[key],
                "value_type": "number",
                "category": "Test",
            }
        )
    saved = client.put(
        "/v1/catalogue",
        json={"expected_revision": current["revision"], "document": document},
    )
    saved.raise_for_status()
    snapshot = saved.json()
    assert all(
        snapshot["runtime"]["bindings"][reading_id]["policy"]["mode"] == "off"
        for reading_id in reading_ids
    )
    applied = client.put(
        "/v1/recording",
        json={
            "expected_revision": snapshot["revision"],
            "expected_collection_revision": snapshot["runtime"]["collection_revision"],
            "reading_ids": list(reading_ids),
            "policy": {"mode": "original", "interval_seconds": 10},
        },
    )
    applied.raise_for_status()
    runtime = applied.json()["runtime"]
    revision = runtime["collection_revision"]
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        status = client.post(
            "/v1/recording/status", json={"reading_ids": list(reading_ids)}
        )
        status.raise_for_status()
        state = status.json()["runtime"]
        if (
            state["collection"].get("revision") == revision
            and state["collection"].get("status") == "applied"
            and state["ingress"].get("sources", {}).get(broker_id, {}).get("state")
            == "connected"
        ):
            break
        time.sleep(1)
    else:
        pytest.fail("Selected generic test inputs did not connect and apply")
    bindings = runtime["bindings"]
    return RecordedEntity(
        broker_id=broker_id,
        device_id=device_id,
        reading_ids=reading_ids,
        entity_id=bindings[reading_ids[0]]["entity_id"],
        topics=topics,
        keys={
            key: bindings[reading_id]["telemetry_key"]
            for key, reading_id in zip(keys, reading_ids, strict=True)
        },
        accepted_topics=tuple(
            bindings[reading_id]["accepted_topic"] for reading_id in reading_ids
        ),
    )


def remove_recorded_entity(client: httpx.Client, entity: RecordedEntity) -> None:
    # A successful stop request releases its activation's input claims
    # asynchronously. Retry conflicts on a fresh revision, as browser cleanup does.
    deadline = time.monotonic() + 90
    while True:
        response = client.get("/v1/catalogue")
        response.raise_for_status()
        current = response.json()
        document = current["document"]
        document["readings"] = [
            reading
            for reading in document["readings"]
            if reading["id"] not in entity.reading_ids
        ]
        document["devices"] = [
            device for device in document["devices"] if device["id"] != entity.device_id
        ]
        document["brokers"] = [
            broker for broker in document["brokers"] if broker["id"] != entity.broker_id
        ]
        removed = client.put(
            "/v1/catalogue",
            json={
                "expected_revision": current["revision"],
                "document": document,
                "pause_affected_monitors": True,
            },
        )
        if removed.status_code != 409 or time.monotonic() >= deadline:
            removed.raise_for_status()
            return
        time.sleep(1)
