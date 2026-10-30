"""Public-API fixtures for the explicitly enabled, disposable stack tests."""

import time
from dataclasses import dataclass
from uuid import uuid4

import httpx
import pytest


@dataclass(frozen=True)
class RecordedEntity:
    connection_id: str
    device_id: str
    stream_ids: tuple[str, ...]
    entity_id: str
    keys: dict[str, str]
    topics: dict[str, str]
    accepted_topics: tuple[str, ...]


def add_recorded_entity(
    client: httpx.Client, *, label: str, keys: tuple[str, ...]
) -> RecordedEntity:
    """Importing structure stays Off; a second action opts these inputs in."""
    identity = uuid4().hex
    connection_id, device_id = f"test-broker-{identity}", f"test-entity-{identity}"
    stream_ids = tuple(f"test-reading-{identity}-{key}" for key in keys)
    topics = {key: f"tests/{identity}/{key}" for key in keys}
    response = client.get("/v1/system")
    response.raise_for_status()
    current = response.json()
    document = current["document"]
    document["connections"].append(
        {
            "id": connection_id,
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
            "connection_id": connection_id,
            "kind": "entity",
        }
    )
    for key, stream_id in zip(keys, stream_ids, strict=True):
        document["streams"].append(
            {
                "id": stream_id,
                "label": key,
                "connection_id": connection_id,
                "device_id": device_id,
                "topic": topics[key],
                "value_type": "number",
                "category": "Test",
            }
        )
    saved = client.put(
        "/v1/system",
        json={"expected_revision": current["revision"], "document": document},
    )
    saved.raise_for_status()
    snapshot = saved.json()
    assert all(
        snapshot["runtime"]["bindings"][stream_id]["policy"]["mode"] == "off"
        for stream_id in stream_ids
    )
    applied = client.put(
        "/v1/system/collection",
        json={
            "expected_revision": snapshot["revision"],
            "expected_collection_revision": snapshot["runtime"]["collection_revision"],
            "stream_ids": list(stream_ids),
            "policy": {"mode": "original", "interval_seconds": 10},
        },
    )
    applied.raise_for_status()
    runtime = applied.json()["runtime"]
    revision = runtime["collection_revision"]
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        status = client.post(
            "/v1/system/collection/status", json={"stream_ids": list(stream_ids)}
        )
        status.raise_for_status()
        state = status.json()["runtime"]
        if (
            state["collection"].get("revision") == revision
            and state["collection"].get("status") == "applied"
            and state["ingress"].get("sources", {}).get(connection_id, {}).get("state")
            == "connected"
        ):
            break
        time.sleep(1)
    else:
        pytest.fail("Selected generic test inputs did not connect and apply")
    bindings = runtime["bindings"]
    return RecordedEntity(
        connection_id=connection_id,
        device_id=device_id,
        stream_ids=stream_ids,
        entity_id=bindings[stream_ids[0]]["entity_id"],
        topics=topics,
        keys={
            key: bindings[stream_id]["telemetry_key"]
            for key, stream_id in zip(keys, stream_ids, strict=True)
        },
        accepted_topics=tuple(
            bindings[stream_id]["accepted_topic"] for stream_id in stream_ids
        ),
    )


def remove_recorded_entity(client: httpx.Client, entity: RecordedEntity) -> None:
    # A successful stop request releases its activation's input claims
    # asynchronously. Retry conflicts on a fresh revision, as browser cleanup does.
    deadline = time.monotonic() + 90
    while True:
        response = client.get("/v1/system")
        response.raise_for_status()
        current = response.json()
        document = current["document"]
        document["streams"] = [
            stream
            for stream in document["streams"]
            if stream["id"] not in entity.stream_ids
        ]
        document["devices"] = [
            device for device in document["devices"] if device["id"] != entity.device_id
        ]
        document["connections"] = [
            connection
            for connection in document["connections"]
            if connection["id"] != entity.connection_id
        ]
        removed = client.put(
            "/v1/system",
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
