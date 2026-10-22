"""Real PostgreSQL, signed membership and HTTP serialization of bounded reports."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from jose import jwt
from off_key_core.config.auth import get_auth_settings
from off_key_core.db.base import get_db_async
from off_key_core.db.models import PipelineRun, User
from off_key_core.models.pipeline_reports import MAX_PIPELINE_REPORT_BYTES
from off_key_core.models.pipelines import execution_fingerprint, pipeline_catalog
from off_key_core.schemas.pipelines import (
    BoundInput,
    PipelineCreate,
    PipelineExecutionConfig,
    PipelinePublish,
)
from off_key_core.schemas.radar import RadarStartConfig
from off_key_core.utils.enum import RoleEnum
from off_key_core.utils.mqtt_topics import derive_monitoring_sensor_keys
from off_key_tactic_middleware.api.v1.pipelines import router
from off_key_tactic_middleware.config.config import get_tactic_settings
from off_key_tactic_middleware.services.pipelines.library import PipelineLibrary

from . import test_monitoring_pipelines_integration as pipeline_integration
from .test_pipeline_report_bounds import maximum_definition

pytestmark = pytest.mark.radar_integration

pipeline_database = pipeline_integration.pipeline_database


def membership_token(user):
    settings = get_auth_settings()
    return jwt.encode(
        {
            "sub": user.email,
            "user_id": user.id,
            "session_version": user.session_version,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
        },
        settings.JWT_SECRET.get_secret_value(),
        algorithm=settings.ALGORITHM,
    )


def bound_execution(revision):
    topics = [f"telemetry/device/r{index}" for index in range(100)]
    keys = derive_monitoring_sensor_keys(topics, sensor_key_strategy="full_hierarchy")
    bindings = [
        BoundInput(
            slot_id=slot.id,
            reading_id=f"r{index}",
            entity_id="device",
            accepted_topic=topics[index],
            input_key=keys[index],
        )
        for index, slot in enumerate(revision.definition.input_slots)
    ]
    return PipelineExecutionConfig(
        definition=revision.definition,
        bindings=bindings,
        revision_id=revision.id,
        run_id=str(uuid4()),
        fingerprint=execution_fingerprint(revision.definition, bindings),
    )


@pytest.mark.asyncio
async def test_http_reports_are_bounded_and_member_can_inspect_selected_run(
    pipeline_database, monkeypatch
):
    monkeypatch.setenv("JWT_SECRET", "pipeline-report-integration-secret-" + "x" * 32)
    monkeypatch.setenv("ALGORITHM", "HS256")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    monkeypatch.setenv("SUPERUSER_MAIL", "report-admin@example.com")
    get_auth_settings.cache_clear()
    try:
        async with pipeline_database() as session:
            library = PipelineLibrary(session)
            design = await library.create(
                PipelineCreate(name="Maximum report", definition=maximum_definition())
            )
            revision = await library.publish(
                design.id, PipelinePublish(expected_version=1)
            )
            execution = bound_execution(revision)
            config = RadarStartConfig(
                container_name="historical-maximum",
                mqtt_topics=[binding.accepted_topic for binding in execution.bindings],
                pipeline=execution,
            )
            service_id = str(uuid4())
            session.add(
                PipelineRun(
                    id=execution.run_id,
                    service_id=service_id,
                    revision_id=revision.id,
                    execution=execution.model_dump(mode="json"),
                    launch_config=config.model_dump(mode="json"),
                    layout={},
                    status="stopped",
                    ended_at=datetime.now(UTC),
                )
            )
            users = [
                User(
                    email=f"report-{role}@example.com",
                    hashed_password="fixture-only",
                    role=role,
                    is_active=True,
                    is_verified=True,
                )
                for role in (RoleEnum.admin, RoleEnum.user)
            ]
            session.add_all(users)
            await session.commit()
            admin_token, member_token = map(membership_token, users)
        app = FastAPI()
        app.include_router(router, prefix="/api/v1")

        async def database_session():
            async with pipeline_database() as session:
                yield session

        app.dependency_overrides[get_db_async] = database_session
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://fixture"
        ) as client:
            apply_body = {
                "definition": pipeline_catalog()
                .templates[0]
                .definition.model_dump(mode="json"),
                "bindings": {"value": "current"},
                "display_name": "HTTP apply",
                "idempotency_key": "http-apply",
            }
            denied = await client.post(
                "/api/v1/monitors/pipelines/apply",
                headers={"Authorization": f"Bearer {member_token}"},
                json=apply_body,
            )
            assert denied.status_code == 403, denied.text[:1000]
            applied = await client.post(
                "/api/v1/monitors/pipelines/apply",
                headers={"Authorization": f"Bearer {admin_token}"},
                json=apply_body,
            )
            assert applied.status_code == 202, applied.text[:1000]
            retried = await client.post(
                "/api/v1/monitors/pipelines/apply",
                headers={"Authorization": f"Bearer {admin_token}"},
                json=apply_body,
            )
            assert retried.status_code == 202
            assert retried.json()["id"] == applied.json()["id"]
            selected = "p59_" + "x" * 96
            response = await client.post(
                f"/api/v1/monitors/pipelines/{design.id}/validate",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "definition": maximum_definition().model_dump(mode="json"),
                    "selected_node_id": selected,
                },
            )
            assert response.status_code == 200, response.text[:1000]
            assert len(response.content) <= MAX_PIPELINE_REPORT_BYTES
            assert len(response.json()["features"][selected]) == 100
            response = await client.post(
                "/api/v1/monitors/pipelines/validate",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "definition": maximum_definition().model_dump(mode="json"),
                    "selected_node_id": selected,
                },
            )
            assert response.status_code == 200, response.text[:1000]
            assert len(response.content) <= MAX_PIPELINE_REPORT_BYTES
            assert len(response.json()["features"][selected]) == 100
            response = await client.post(
                "/api/v1/monitors/pipelines/validate",
                headers={"Authorization": f"Bearer {member_token}"},
                json={"definition": maximum_definition().model_dump(mode="json")},
            )
            assert response.status_code == 403, response.text[:1000]
            invalid = maximum_definition().model_dump(mode="json")
            invalid["nodes"][0]["params"] = {"😺" * 100_000: "unknown"}
            response = await client.post(
                f"/api/v1/monitors/pipelines/{design.id}/validate",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"definition": invalid, "selected_node_id": "input"},
            )
            assert response.status_code == 200, response.text[:1000]
            assert len(response.content) <= MAX_PIPELINE_REPORT_BYTES
            invalid_report = response.json()
            assert not invalid_report["valid"]
            assert invalid_report["definition"] is None
            assert invalid_report["definition_omitted"]
            assert invalid_report["issues_truncated"]
            assert all(
                len(issue["message"].encode("utf-8")) <= 1024
                for issue in invalid_report["issues"]
            )
            monkeypatch.setenv("TACTIC_PIPELINE_AUTHORING_ENABLED", "false")
            get_tactic_settings.cache_clear()
            response = await client.get(
                f"/api/v1/monitors/{service_id}/pipeline",
                params={"selected_node_id": selected},
                headers={"Authorization": f"Bearer {member_token}"},
            )
            assert response.status_code == 200, response.text[:1000]
            report = response.json()["validation"]
            assert len(report["features"][selected]) == 100
            assert not report["features_complete"] and not report["provenance_complete"]
            assert (
                len(httpx.Response(200, json=report).content)
                <= MAX_PIPELINE_REPORT_BYTES
            )
            response = await client.get(
                f"/api/v1/monitors/{service_id}/pipeline",
                params={"selected_node_id": "removed_node"},
                headers={"Authorization": f"Bearer {member_token}"},
            )
            assert response.status_code == 200, response.text[:1000]
            report = response.json()["validation"]
            assert report["features"] == {}
            assert "selected_node" in {issue["code"] for issue in report["issues"]}
            response = await client.get(
                f"/api/v1/monitors/{service_id}/pipeline-metadata",
                params={"selected_node_id": selected},
                headers={"Authorization": f"Bearer {member_token}"},
            )
            assert response.status_code == 200, response.text[:1000]
            focused = response.json()
            assert focused["definition"] is None and focused["definition_omitted"]
            assert "history" not in focused and "run" not in focused
            assert len(focused["features"][selected]) == 100
            assert len(focused["features"]) <= 2
            assert len(response.content) <= MAX_PIPELINE_REPORT_BYTES
            response = await client.get(
                f"/api/v1/monitors/pipelines/{design.id}/revisions/{revision.id}/metadata",
                params={"selected_node_id": selected},
                headers={"Authorization": f"Bearer {member_token}"},
            )
            assert response.status_code == 200, response.text[:1000]
            assert response.json()["features"] == focused["features"]
            response = await client.post(
                f"/api/v1/monitors/pipelines/{design.id}/validate",
                headers={"Authorization": f"Bearer {member_token}"},
                json={"definition": maximum_definition().model_dump(mode="json")},
            )
            assert response.status_code == 403
    finally:
        get_auth_settings.cache_clear()
