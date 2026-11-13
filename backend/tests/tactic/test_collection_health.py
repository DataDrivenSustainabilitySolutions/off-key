"""Members read collection health with the server's diagnosis attached."""

from unittest.mock import AsyncMock

from off_key_core.db.collection_runtime import CollectionRuntimeSnapshot
from off_key_core.schemas.system import SystemDocument
from off_key_core.schemas.system_collection import SystemCollectionDefinition
from off_key_tactic_middleware.services.catalogue import system as system_service

from tests.support.gateway import gateway_app, member
from tests.support.http import asgi_client


async def test_health_carries_the_diagnosis_next_to_the_raw_reports(monkeypatch):
    collection = {"status": "starting", "counters": {"invalid": 0}}
    ingress = {"status": "connecting", "sources": {}}
    monkeypatch.setattr(
        system_service,
        "read_collection_runtime",
        AsyncMock(
            return_value=CollectionRuntimeSnapshot(
                revision=0,
                catalog=SystemCollectionDefinition(
                    document=SystemDocument(), bindings={}
                ),
                ingress=ingress,
                collection=collection,
            )
        ),
    )
    async with asgi_client(gateway_app(member())) as client:
        response = await client.get("/v1/recording/health")
    assert response.status_code == 200
    body = response.json()
    assert body["collection"] == collection
    assert body["ingress"] == ingress
    diagnosis = body.pop("diagnosis")
    assert set(body) == {"revision", "collection", "ingress"}
    assert diagnosis["code"] == "not_configured"
    assert diagnosis["tone"] == "neutral"
    assert diagnosis["title"] == "Not configured"
    assert diagnosis["measurements_current"] is False
