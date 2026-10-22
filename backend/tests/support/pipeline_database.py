"""Real PostgreSQL pipeline fixture with an applied fixture catalogue."""

from datetime import UTC, datetime, timedelta

import pytest_asyncio
from jose import jwt
from off_key_core.config.auth import get_auth_settings
from off_key_core.db.migrate import apply_migrations
from off_key_core.db.models import (
    SystemCollectionConfiguration,
)
from off_key_core.models.pipelines import pipeline_catalog
from off_key_core.schemas.pipelines import (
    PipelineCreate,
    PipelinePublish,
)
from off_key_core.schemas.system import SystemDocument
from off_key_core.schemas.system_collection import (
    SystemCollectionDefinition,
    build_bindings,
)
from off_key_tactic_middleware.config.config import get_tactic_settings
from off_key_tactic_middleware.services.pipelines.library import PipelineLibrary
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def pipeline_database(disposable_database, monkeypatch):
    monkeypatch.setenv("TACTIC_PIPELINE_AUTHORING_ENABLED", "true")
    get_tactic_settings.cache_clear()
    with disposable_database.begin() as connection:
        apply_migrations(connection)
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    document = SystemDocument.model_validate(
        {
            "connections": [{"id": "broker", "label": "Fixture", "host": "localhost"}],
            "devices": [
                {"id": "device", "label": "Device", "connection_id": "broker"},
                {"id": "other", "label": "Other", "connection_id": "broker"},
            ],
            "streams": [
                {
                    "id": "current",
                    "label": "Current",
                    "connection_id": "broker",
                    "device_id": "device",
                    "topic": "fixture/current",
                    "unit": "A",
                },
                {
                    "id": "temperature",
                    "label": "Temperature",
                    "connection_id": "broker",
                    "device_id": "device",
                    "topic": "fixture/temperature",
                    "unit": "C",
                },
                {
                    "id": "other_current",
                    "label": "Other current",
                    "connection_id": "broker",
                    "device_id": "other",
                    "topic": "other/current",
                    "unit": "A",
                },
            ],
            "default_policy": {"mode": "original"},
        }
    )
    definition = SystemCollectionDefinition(
        document=document, bindings=build_bindings(document)
    )
    async with sessions.begin() as session:
        session.add(
            SystemCollectionConfiguration(
                id=1,
                revision=1,
                document=definition.model_dump(mode="json"),
                ingress_status={},
                collection_status={"revision": 1, "status": "applied"},
                updated_by="integration",
            )
        )
    try:
        yield sessions
    finally:
        await engine.dispose()
        get_tactic_settings.cache_clear()


async def published_design(session):
    definition = pipeline_catalog().templates[0].definition
    library = PipelineLibrary(session)
    design = await library.create(
        PipelineCreate(name="Integration graph", definition=definition)
    )
    revision = await library.publish(
        design.id, PipelinePublish(expected_version=design.version)
    )
    return design, revision


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
