"""Catalog names are durable metadata; editing them must not reapply collection."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from jose import jwt
from off_key_api_gateway.api.v1 import collection as gateway
from off_key_core.config.auth import get_auth_settings
from off_key_core.db.base import get_db_async
from off_key_core.db.models import (
    Charger,
    CollectionBinding,
    CollectionConfiguration,
    CollectionRevision,
    CollectionState,
    User,
)
from off_key_core.db.system import SystemCollectionConfiguration
from off_key_core.schemas.collection import (
    CatalogLabelChange,
    CatalogSnapshot,
    collection_runtime_configuration,
)
from off_key_core.utils.enum import RoleEnum
from off_key_tactic_middleware.api.v1 import collection as api
from off_key_tactic_middleware.domain import ConflictError, NotFoundError
from off_key_tactic_middleware.services import collection
from pydantic import ValidationError
from sqlalchemy import JSON, MetaData, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import sessionmaker

from .test_collection import catalog
from .test_gateway_auth_token_types import _set_auth_env


def rename_request(configuration, kind="sensor", **overrides):
    source = configuration.sources[0]
    charger = source.chargers[0]
    payload = {
        "expected_revision": 3,
        "kind": kind,
        "source_id": source.id,
        "label": "  Assembly reading  ",
    }
    if kind != "source":
        payload["charger_id"] = charger.id
    if kind == "sensor":
        payload["sensor_key"] = charger.sensors[0].key
    return CatalogLabelChange.model_validate({**payload, **overrides})


@pytest.fixture
def saved_catalog(monkeypatch, tmp_path):
    """Exercise real ORM writes on a private disposable SQLite test database."""
    engine = create_engine(f"sqlite:///{tmp_path / 'catalog-labels.db'}")
    metadata = MetaData()
    SystemCollectionConfiguration.__table__.to_metadata(metadata)
    models = (
        CollectionConfiguration,
        CollectionRevision,
        Charger,
        CollectionBinding,
        CollectionState,
    )
    for model in models:
        table = model.__table__.to_metadata(metadata)
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    configuration = catalog("sample")
    source = configuration.sources[0]
    source.forward_port = 20000
    charger = source.chargers[0]
    now = datetime.now(UTC)
    ingress = {
        "revision": 3,
        "status": "applied",
        "checked_at": now.isoformat(),
        "sources": {str(source.id): {"status": "connected"}},
    }
    collection_state = {
        "revision": 3,
        "status": "applied",
        "records_written": 12,
        "counters": {"accepted": 42},
        "diagnostics": {"sample_slots": 1},
    }
    with sessions.begin() as session:
        session.add(
            CollectionConfiguration(
                id=1,
                revision=3,
                document=configuration.model_dump(mode="json"),
                ingress_status=ingress,
                collection_status=collection_state,
                updated_at=now,
                updated_by="previous@example.invalid",
            )
        )
        session.add(
            Charger(
                charger_id=str(charger.id),
                charger_name=charger.label,
                online=True,
                mqtt_connected=True,
                state="charging",
                mqtt_error_count=2,
                mqtt_last_message=now,
            )
        )
        session.add(
            CollectionBinding(
                charger_id=str(charger.id),
                source_id=str(source.id),
                local_id=charger.local_id,
            )
        )
        session.add(
            CollectionState(
                charger_id=str(charger.id),
                sensor_key=charger.sensors[0].key,
                value=42,
                received_at=now,
                is_snapshot=False,
            )
        )
    lock = AsyncMock()
    writes = AsyncMock()
    monkeypatch.setattr(collection, "lock_collection_configuration", lock)
    monkeypatch.setattr(collection, "require_application_writes", writes)
    try:
        yield SimpleNamespace(
            sessions=sessions,
            catalog=configuration,
            ingress=ingress,
            collection=collection_state,
            lock=lock,
            writes=writes,
        )
    finally:
        engine.dispose()


def service_for(session):
    async_session = SimpleNamespace(
        scalar=AsyncMock(side_effect=session.scalar),
        execute=AsyncMock(side_effect=session.execute),
        flush=AsyncMock(side_effect=session.flush),
        add=MagicMock(side_effect=session.add),
    )
    service = collection.CollectionService(async_session)
    service._pause_monitors = AsyncMock()
    service._update_bindings = AsyncMock()
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["source", "charger", "sensor"])
async def test_rename_persists_only_label_and_audits_without_resetting_live_state(
    saved_catalog, kind
):
    fixture = saved_catalog
    request = rename_request(fixture.catalog, kind)
    before = collection_runtime_configuration(fixture.catalog)
    with fixture.sessions.begin() as session:
        service = service_for(session)
        result = await service.rename(request, actor="admin@example.invalid")
        service._pause_monitors.assert_not_awaited()
        service._update_bindings.assert_not_awaited()
    fixture.lock.assert_awaited_once()
    fixture.writes.assert_awaited_once()
    assert result.revision == 4 and result.updated_by == "admin@example.invalid"
    assert collection_runtime_configuration(result.catalog) == before
    assert result.ingress == {**fixture.ingress, "revision": 4}
    assert result.collection == {**fixture.collection, "revision": 4}
    source = result.catalog.sources[0]
    charger = source.chargers[0]
    target = (
        source
        if kind == "source"
        else charger
        if kind == "charger"
        else charger.sensors[0]
    )
    assert target.label == "Assembly reading"
    expected = fixture.catalog.model_copy(deep=True)
    expected_source = expected.sources[0]
    expected_charger = expected_source.chargers[0]
    expected_target = (
        expected_source
        if kind == "source"
        else expected_charger
        if kind == "charger"
        else expected_charger.sensors[0]
    )
    expected_target.label = request.label
    assert result.catalog == expected
    with fixture.sessions() as session:
        persisted = session.get(CollectionConfiguration, 1)
        audit = session.get(CollectionRevision, 4)
        assert persisted.document == result.catalog.model_dump(mode="json")
        assert (
            audit.document == persisted.document
            and audit.updated_by == result.updated_by
        )
        hardware = session.get(Charger, str(charger.id))
        assert hardware.charger_name == (
            request.label
            if kind == "charger"
            else fixture.catalog.sources[0].chargers[0].label
        )
        assert (
            hardware.online and hardware.mqtt_connected and hardware.state == "charging"
        )
        assert hardware.mqtt_error_count == 2 and hardware.mqtt_last_message is not None
        binding = session.get(CollectionBinding, str(charger.id))
        assert (
            binding.source_id == str(source.id) and binding.local_id == charger.local_id
        )
        observation = session.get(
            CollectionState, (str(charger.id), charger.sensors[0].key)
        )
        assert observation.value == 42 and not observation.is_snapshot


@pytest.mark.asyncio
async def test_rename_rejects_stale_revisions_and_leaves_database_unchanged(
    saved_catalog,
):
    with (
        saved_catalog.sessions.begin() as session,
        pytest.raises(ConflictError, match="Reload"),
    ):
        await service_for(session).rename(
            rename_request(saved_catalog.catalog, expected_revision=2),
            actor="admin@example.invalid",
        )
    with saved_catalog.sessions() as session:
        assert session.get(CollectionConfiguration, 1).revision == 3
        assert session.scalars(select(CollectionRevision)).all() == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["source", "charger", "sensor"])
async def test_rename_unknown_or_mismatched_identity_is_atomic(saved_catalog, kind):
    overrides = (
        {"source_id": uuid4()}
        if kind == "source"
        else {"charger_id": uuid4()}
        if kind == "charger"
        else {"sensor_key": "missing"}
    )
    with saved_catalog.sessions.begin() as session, pytest.raises(NotFoundError):
        await service_for(session).rename(
            rename_request(saved_catalog.catalog, kind, **overrides),
            actor="admin@example.invalid",
        )
    with saved_catalog.sessions() as session:
        row = session.get(CollectionConfiguration, 1)
        assert row.revision == 3 and row.document == saved_catalog.catalog.model_dump(
            mode="json"
        )
        assert session.scalars(select(CollectionRevision)).all() == []


@pytest.mark.asyncio
async def test_rename_cannot_address_a_charger_under_another_saved_broker(
    saved_catalog,
):
    second = catalog().sources[0]
    second.host = "other.ts.net"
    expanded = saved_catalog.catalog.model_copy(deep=True)
    expanded.sources.append(second)
    with saved_catalog.sessions.begin() as session:
        row = session.get(CollectionConfiguration, 1)
        row.document = expanded.model_dump(mode="json")
    with saved_catalog.sessions.begin() as session, pytest.raises(NotFoundError):
        await service_for(session).rename(
            rename_request(expanded, "charger", source_id=second.id),
            actor="admin@example.invalid",
        )
    with saved_catalog.sessions() as session:
        assert session.get(CollectionConfiguration, 1).revision == 3


@pytest.mark.asyncio
async def test_unchanged_label_is_idempotent_and_stale_worker_status_is_not_promoted(
    saved_catalog,
):
    with saved_catalog.sessions.begin() as session:
        row = session.get(CollectionConfiguration, 1)
        row.ingress_status = {"revision": 2, "status": "applying"}
        service = service_for(session)
        old_label = saved_catalog.catalog.sources[0].label
        unchanged = await service.rename(
            rename_request(saved_catalog.catalog, "source", label=old_label),
            actor="admin@example.invalid",
        )
        assert (
            unchanged.revision == 3
            and unchanged.updated_by == "previous@example.invalid"
        )
        renamed = await service.rename(
            rename_request(saved_catalog.catalog, "source"),
            actor="admin@example.invalid",
        )
        assert renamed.revision == 4 and renamed.ingress == {
            "revision": 2,
            "status": "applying",
        }
    with saved_catalog.sessions() as session:
        assert len(session.scalars(select(CollectionRevision)).all()) == 1


@pytest.mark.parametrize(
    "label", ["", " ", "a" * 121, "line\nbreak", "nul\0", "control\x7f"]
)
def test_rename_rejects_invalid_labels(label):
    with pytest.raises(ValidationError):
        rename_request(catalog(), label=label)


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "source", "charger_id": uuid4()},
        {"kind": "charger", "charger_id": None},
        {"kind": "charger", "sensor_key": "temperature"},
        {"kind": "sensor", "sensor_key": None},
        {"policy": {"mode": "off"}},
        {"host": "replacement.example.invalid"},
    ],
)
def test_rename_payload_cannot_change_runtime_fields_or_omit_identity(overrides):
    with pytest.raises(ValidationError):
        rename_request(catalog(), **overrides)


@pytest.mark.asyncio
async def test_rename_http_requires_verified_current_administrator_and_audits_actor(
    monkeypatch,
):
    _set_auth_env(monkeypatch)
    settings = get_auth_settings()
    user = User(
        id=1,
        email="admin@example.invalid",
        is_verified=False,
        is_active=True,
        session_version=0,
        role=RoleEnum.user,
    )
    session = AsyncMock()
    session.scalar.return_value = user
    configuration = catalog()
    request = rename_request(configuration)
    response = CatalogSnapshot(revision=4, catalog=configuration)
    rename = AsyncMock(return_value=response)
    monkeypatch.setattr(
        api, "CollectionService", lambda _: SimpleNamespace(rename=rename)
    )
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_db_async] = lambda: session
    token = jwt.encode(
        {
            "sub": user.email,
            "user_id": user.id,
            "session_version": 0,
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "iss": settings.JWT_ISSUER,
            "aud": settings.JWT_AUDIENCE,
        },
        settings.JWT_SECRET.get_secret_value(),
        algorithm=settings.ALGORITHM,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        body = request.model_dump(mode="json")
        assert (await client.patch("/collection/labels", json=body)).status_code == 401
        headers = {"Authorization": f"Bearer {token}"}
        assert (
            await client.patch("/collection/labels", json=body, headers=headers)
        ).status_code == 401
        user.is_verified = True
        assert (
            await client.patch("/collection/labels", json=body, headers=headers)
        ).status_code == 403
        rename.assert_not_awaited()
        user.role = RoleEnum.admin
        result = await client.patch("/collection/labels", json=body, headers=headers)
        assert result.status_code == 200 and result.json() == response.model_dump(
            mode="json"
        )
        rename.assert_awaited_once_with(request, actor=user.email)
        invalid = await client.patch(
            "/collection/labels", json={**body, "label": " "}, headers=headers
        )
        assert invalid.status_code == 422 and rename.await_count == 1


@pytest.mark.asyncio
async def test_gateway_forwards_authenticated_metadata_only_rename(monkeypatch):
    request = rename_request(catalog())
    forward = AsyncMock(return_value={"revision": 4})
    monkeypatch.setattr(gateway.tactic, "_make_request", forward)
    with pytest.raises(HTTPException) as missing:
        await gateway.rename_catalog_entity(request, None)
    assert missing.value.status_code == 401
    forward.assert_not_awaited()
    assert await gateway.rename_catalog_entity(request, "Bearer access-token") == {
        "revision": 4
    }
    forward.assert_awaited_once_with(
        "PATCH",
        "/api/v1/collection/labels",
        json_data=request.model_dump(mode="json"),
        headers={"Authorization": "Bearer access-token"},
    )
