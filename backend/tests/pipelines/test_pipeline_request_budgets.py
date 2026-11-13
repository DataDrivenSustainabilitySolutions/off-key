"""Real API limiting, signed auth and PostgreSQL writes."""

import httpx
import pytest
from off_key_api_gateway.api.rate_limiter import limiter
from off_key_core.auth.permissions import ADMIN_ROLE
from off_key_core.config.auth import get_auth_settings
from off_key_core.db.models import User
from off_key_core.models.pipelines import pipeline_catalog
from off_key_core.schemas.pipelines import PipelineCreate
from off_key_tactic_middleware.services.pipelines.library import PipelineLibrary
from slowapi.middleware import SlowAPIMiddleware

from tests.support.gateway import gateway_app
from tests.support.pipeline_database import membership_token


@pytest.mark.asyncio
async def test_automatic_compilation_cannot_exhaust_writes_or_polling(
    pipeline_database, monkeypatch
):
    monkeypatch.setenv("JWT_SECRET", "pipeline-budget-integration-secret-" + "x" * 32)
    monkeypatch.setenv("SUPERUSER_MAIL", "budget-admin@example.com")
    monkeypatch.setenv("ALGORITHM", "HS256")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    get_auth_settings.cache_clear()
    limiter.reset()
    definition = pipeline_catalog().templates[0].definition
    async with pipeline_database() as session:
        user = User(
            email="budget-admin@example.com",
            hashed_password="fixture-only",
            role=ADMIN_ROLE,
            is_active=True,
            is_verified=True,
        )
        session.add(user)
        design = await PipelineLibrary(session).create(
            PipelineCreate(
                name="Independent request budgets",
                definition=definition,
            )
        )
        token = membership_token(user)
    gateway = gateway_app(sessions=pipeline_database)
    gateway.add_middleware(SlowAPIMiddleware)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gateway),
            base_url="http://gateway",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            path = f"/v1/pipelines/{design.id}"
            for _ in range(31):
                response = await client.post(
                    path + "/validate",
                    json={
                        "definition": definition.model_dump(mode="json"),
                    },
                )
                assert response.status_code == 200, response.text[:1000]
            response = await client.put(
                path + "/draft",
                json={
                    "expected_version": 1,
                    "definition": definition.model_dump(mode="json"),
                    "name": "Saved after 31 inspections",
                    "description": "Atomic metadata",
                },
            )
            assert response.status_code == 200, response.text[:1000]
            assert response.json()["name"] == "Saved after 31 inspections"
            response = await client.post(
                path + "/revisions", json={"expected_version": 2}
            )
            assert response.status_code == 201, response.text[:1000]
            for _ in range(89):
                response = await client.post(
                    path + "/validate",
                    json={
                        "definition": definition.model_dump(mode="json"),
                    },
                )
                assert response.status_code == 200, response.text[:1000]
            response = await client.post(
                path + "/validate",
                json={
                    "definition": definition.model_dump(mode="json"),
                },
            )
            assert response.status_code == 429
            assert (await client.get(path)).status_code == 200
            response = await client.put(
                path + "/draft",
                json={
                    "expected_version": 3,
                    "definition": definition.model_dump(mode="json"),
                },
            )
            assert response.status_code == 200, response.text[:1000]
    finally:
        limiter.reset()
