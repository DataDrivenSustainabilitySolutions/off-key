"""Members read collection health with the server's diagnosis attached."""

from unittest.mock import AsyncMock

from fastapi import FastAPI
from off_key_core.auth.permissions import MEMBER_ROLE
from off_key_core.db.base import get_db_async
from off_key_core.db.collection_runtime import CollectionRuntimeSnapshot
from off_key_core.db.models import User
from off_key_core.schemas.system import SystemDocument
from off_key_core.schemas.system_collection import SystemCollectionDefinition
from off_key_tactic_middleware.api.collection_auth import current_caller
from off_key_tactic_middleware.api.v1 import system as system_api
from off_key_tactic_middleware.services.catalogue import system as system_service

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
    app = FastAPI()
    app.include_router(system_api.router)
    app.dependency_overrides[current_caller] = lambda: User(
        id=1, email="member@example.com", role=MEMBER_ROLE
    )
    app.dependency_overrides[get_db_async] = lambda: AsyncMock()
    async with asgi_client(app) as client:
        response = await client.get("/system/health")
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
