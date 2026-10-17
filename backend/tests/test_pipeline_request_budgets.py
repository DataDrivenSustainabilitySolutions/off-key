"""Real gateway limiting, HTTP forwarding, signed auth and PostgreSQL writes."""

import asyncio

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from off_key_api_gateway.api.rate_limiter import limiter, rate_limit_exceeded_handler
from off_key_api_gateway.api.v1.pipelines import router as gateway_router
from off_key_api_gateway.facades.tactic import get_tactic_client, tactic
from off_key_core.config.auth import get_auth_settings
from off_key_core.config.service_auth import get_service_auth_settings
from off_key_core.db.base import get_db_async
from off_key_core.db.models import User
from off_key_core.models.pipelines import pipeline_catalog
from off_key_core.schemas.pipelines import PipelineCreate
from off_key_core.utils.enum import RoleEnum
from off_key_tactic_middleware.api.v1.members import router as members_router
from off_key_tactic_middleware.api.v1.pipelines import router as tactic_router
from off_key_tactic_middleware.services.pipelines.library import PipelineLibrary
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from . import test_monitoring_pipelines_integration as integration
from .test_pipeline_report_api import membership_token

pipeline_database = integration.pipeline_database


@pytest.mark.asyncio
async def test_automatic_compilation_cannot_exhaust_writes_or_polling(
    pipeline_database, monkeypatch, unused_tcp_port
):
    monkeypatch.setenv("JWT_SECRET", "pipeline-budget-integration-secret-" + "x" * 32)
    monkeypatch.setenv("SUPERUSER_MAIL", "budget-admin@example.com")
    monkeypatch.setenv("ALGORITHM", "HS256")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    monkeypatch.setenv(
        "INTERNAL_API_SECRET", "pipeline-budget-internal-secret-" + "x" * 32
    )
    get_service_auth_settings.cache_clear()
    get_auth_settings.cache_clear()
    limiter.reset()
    definition = pipeline_catalog().templates[0].definition
    async with pipeline_database() as session:
        user = User(
            email="budget-admin@example.com",
            hashed_password="fixture-only",
            role=RoleEnum.admin,
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
    upstream = FastAPI()
    upstream.include_router(tactic_router, prefix="/api/v1")
    upstream.include_router(members_router, prefix="/api/v1")

    async def database_session():
        async with pipeline_database() as session:
            yield session

    upstream.dependency_overrides[get_db_async] = database_session
    server = uvicorn.Server(
        uvicorn.Config(
            upstream,
            host="127.0.0.1",
            port=unused_tcp_port,
            log_level="warning",
            lifespan="off",
        )
    )
    task = asyncio.create_task(server.serve())
    await tactic.close()
    monkeypatch.setattr(
        get_tactic_client(), "base_url", f"http://127.0.0.1:{unused_tcp_port}"
    )
    gateway = FastAPI()
    gateway.state.limiter = limiter
    gateway.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    gateway.add_middleware(SlowAPIMiddleware)
    gateway.include_router(gateway_router, prefix="/api/v1/monitors")
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                await asyncio.sleep(0.01)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gateway),
            base_url="http://gateway",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            path = f"/api/v1/monitors/pipelines/{design.id}"
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
        server.should_exit = True
        await task
        await tactic.close()
        limiter.reset()
        get_auth_settings.cache_clear()
        get_service_auth_settings.cache_clear()
