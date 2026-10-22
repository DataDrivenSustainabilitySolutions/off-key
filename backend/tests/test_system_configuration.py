"""Saved-system structure, persistence, authorization and legacy non-mutation."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from off_key_api_gateway.api.v1 import system as gateway_system
from off_key_core.db.base import get_db_async
from off_key_core.db.catalogue_v1 import adapt_ambibox_catalog, legacy_stream_id
from off_key_core.db.models import (
    Charger,
    CollectionBinding,
    CollectionConfiguration,
    CollectionRevision,
    User,
)
from off_key_core.db.system import (
    SystemCollectionConfiguration,
    SystemConfiguration,
    SystemRevision,
)
from off_key_core.schemas.collection_policy import CollectionPolicy
from off_key_core.schemas.system import SystemChange, SystemDocument, SystemSnapshot
from off_key_core.schemas.system_collection import SystemCollectionScope
from off_key_core.utils.enum import RoleEnum
from off_key_tactic_middleware.api.collection_auth import current_member
from off_key_tactic_middleware.api.v1 import system as system_api
from off_key_tactic_middleware.domain import ConflictError
from off_key_tactic_middleware.services import system as system_service
from pydantic import ValidationError
from sqlalchemy import JSON, MetaData, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from .test_collection import catalog


@pytest.mark.asyncio
async def test_scoped_status_returns_only_requested_reading_activity(monkeypatch):
    snapshot = SystemSnapshot(
        revision=1,
        document=document(),
        storage_origin="saved",
        runtime={
            "mode": "collection",
            "message": "",
            "bindings": {
                "temperature-1": {"connection_id": "broker-1"},
                "humidity-1": {"connection_id": "broker-2"},
            },
            "ingress": {
                "sources": {
                    "broker-1": {"state": "connected"},
                    "broker-2": {"state": "connected"},
                },
                "readings": {
                    key: {"fresh_received_at": "2026-10-13T12:00:00Z"}
                    for key in ("temperature-1", "humidity-1")
                },
            },
        },
    )
    service = AsyncMock()
    service.read.return_value = snapshot
    service.latest_readings.return_value = {}
    monkeypatch.setattr(system_api, "SystemService", lambda session: service)
    result = await system_api.collection_status(
        SystemCollectionScope(stream_ids=["temperature-1"]), user=None, session=None
    )
    assert set(result["runtime"]["ingress"]["readings"]) == {"temperature-1"}
    assert set(result["runtime"]["ingress"]["sources"]) == {"broker-1"}
    service.latest_readings.assert_awaited_once_with(snapshot.runtime.bindings)


class AsyncSessionAdapter:
    """Use a real disposable SQLite database without an optional async driver."""

    def __init__(self, session):
        self.session = session

    async def scalar(self, statement):
        return self.session.scalar(statement)

    async def scalars(self, statement):
        return self.session.scalars(statement)

    async def execute(self, statement, params=None):
        return self.session.execute(statement, params)

    def add(self, row):
        self.session.add(row)

    async def flush(self):
        self.session.flush()


def document():
    return SystemDocument.model_validate(
        {
            "label": "Workshop",
            "connections": [{"id": "broker-1", "label": "MQTT", "host": "localhost"}],
            "devices": [{"id": "room-1", "label": "Office", "kind": "room"}],
            "streams": [
                {
                    "id": "temperature-1",
                    "label": "Temperature",
                    "connection_id": "broker-1",
                    "device_id": "room-1",
                    "topic": "home/office/environment",
                    "payload_pointer": "/readings/temperature",
                    "unit": "°C",
                }
            ],
            "groups": [
                {
                    "id": "group-1",
                    "label": "Office",
                    "member_ids": ["room-1", "temperature-1"],
                }
            ],
        }
    )


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'system.db'}")
    tables = [
        Charger.__table__,
        CollectionBinding.__table__,
        CollectionConfiguration.__table__,
        CollectionRevision.__table__,
        SystemConfiguration.__table__,
        SystemRevision.__table__,
        SystemCollectionConfiguration.__table__,
    ]
    metadata = MetaData()
    for original in tables:
        table = original.to_metadata(metadata)
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    metadata.create_all(engine)
    monkeypatch.setattr(system_service, "lock_collection_configuration", AsyncMock())
    monkeypatch.setattr(system_service, "require_application_writes", AsyncMock())
    yield engine
    engine.dispose()


@pytest.mark.parametrize(
    "host", ["localhost", "192.168.1.20", "2001:db8::1", "broker.example.com"]
)
def test_generic_connections_accept_hostname_and_ip_addresses(host):
    data = document().model_dump(mode="json")
    data["connections"][0]["host"] = host
    assert SystemDocument.model_validate(data).connections[0].host == host


@pytest.mark.parametrize(
    "topic",
    [
        "factory/press/temperature",
        "weather/東京",
        "/sensors//outside",
        "$SYS/broker/messages/sent",
    ],
)
def test_streams_accept_generic_concrete_mqtt_topics(topic):
    data = document().model_dump(mode="json")
    data["streams"][0]["topic"] = topic
    assert SystemDocument.model_validate(data).streams[0].topic == topic


@pytest.mark.parametrize(
    "section,field,value",
    [
        ("connections", "host", "mqtt://localhost:1883"),
        ("connections", "password", "must-not-save-a-password"),
        ("connections", "websocket_path", "/mqtt"),
        ("streams", "topic", "factory/+/temperature"),
        ("streams", "topic", "factory/#"),
        ("streams", "topic", "invalid\x00topic"),
        ("streams", "topic", "あ" * 200),
        ("streams", "payload_pointer", "readings.temperature"),
        ("streams", "payload_pointer", "/readings/~2"),
        ("streams", "connection_id", "missing"),
        ("streams", "device_id", "missing"),
        ("devices", "parent_id", "room-1"),
        ("devices", "connection_id", "missing"),
        ("connections", "label", " \n "),
        ("connections", "label", "\x00name"),
        ("groups", "member_ids", ["missing"]),
        ("groups", "member_ids", ["room-1", "room-1"]),
        ("groups", "color", "red"),
    ],
)
def test_invalid_structure_and_embedded_secrets_are_rejected(section, field, value):
    data = document().model_dump(mode="json")
    data[section][0][field] = value
    with pytest.raises(ValidationError):
        SystemDocument.model_validate(data)


def test_duplicate_identity_and_parent_cycles_are_rejected():
    data = document().model_dump(mode="json")
    data["devices"][0]["id"] = data["connections"][0]["id"]
    with pytest.raises(ValidationError, match="Stable IDs"):
        SystemDocument.model_validate(data)
    data = document().model_dump(mode="json")
    data["devices"] = [
        {"id": "device-a", "label": "A", "parent_id": "device-b"},
        {"id": "device-b", "label": "B", "parent_id": "device-a"},
    ]
    data["streams"] = []
    data["groups"] = []
    with pytest.raises(ValidationError, match="cycle"):
        SystemDocument.model_validate(data)


@pytest.mark.parametrize("reserved_id", ["__proto__", "constructor", "prototype"])
def test_reserved_configuration_storage_ids_are_rejected(reserved_id):
    data = document().model_dump(mode="json")
    data["connections"][0]["id"] = reserved_id
    data["streams"][0]["connection_id"] = reserved_id
    with pytest.raises(ValidationError, match="reserved"):
        SystemDocument.model_validate(data)


def test_reserved_credential_reference_is_rejected():
    data = document().model_dump(mode="json")
    data["connections"][0]["credential_ref"] = "__proto__"
    with pytest.raises(ValidationError, match="reserved"):
        SystemDocument.model_validate(data)


def test_entity_ids_cannot_conflict_with_collapsed_group_identity():
    data = document().model_dump(mode="json")
    data["connections"][0]["id"] = "group:group-1"
    data["streams"][0]["connection_id"] = "group:group-1"
    with pytest.raises(ValidationError, match="collapsed group identity"):
        SystemDocument.model_validate(data)


def test_group_prefixed_entity_ids_are_valid_when_no_aggregate_collides():
    data = document().model_dump(mode="json")
    data["connections"][0]["id"] = "group:ordinary-connection"
    data["streams"][0]["connection_id"] = "group:ordinary-connection"
    assert (
        SystemDocument.model_validate(data).connections[0].id
        == "group:ordinary-connection"
    )


def test_entity_cannot_belong_to_two_spatial_groups():
    data = document().model_dump(mode="json")
    data["groups"].append(
        {"id": "group-2", "label": "Second", "member_ids": ["room-1"]}
    )
    with pytest.raises(ValidationError, match="at most one"):
        SystemDocument.model_validate(data)


def test_json_pointers_and_websocket_connections_roundtrip():
    data = document().model_dump(mode="json")
    data["connections"][0].update(
        transport="websocket",
        websocket_path="/mqtt",
        tls=True,
        port=443,
        credential_ref="credentials/workshop-mqtt",
    )
    data["streams"][0]["payload_pointer"] = "/readings/temperature~1air~0value"
    parsed = SystemDocument.model_validate_json(
        SystemDocument.model_validate(data).model_dump_json()
    )
    assert parsed.connections[0].credential_ref == "credentials/workshop-mqtt"
    assert parsed.streams[0].payload_pointer == "/readings/temperature~1air~0value"
    assert parsed.default_policy.mode == "off"


@pytest.mark.parametrize(
    "key,fingerprint",
    [
        ("nested/path", "6ad8194d784007ad"),
        ("t" * 160, "0d1ce30ce33d173a"),
        ("温度", "95fa69cf89ff6a76"),
    ],
)
def test_legacy_complex_stream_ids_match_existing_scene_algorithm(key, fingerprint):
    charger_id = "00000000-0000-0000-0000-000000000001"
    assert (
        legacy_stream_id(charger_id, key)
        == f"ambibox:sensor:{charger_id}:key-{fingerprint}"
    )


def test_legacy_adapter_preserves_identity_topics_and_policies_without_mutation():
    original = catalog("sample")
    original.sources[0].chargers[0].sensors[0].policy = CollectionPolicy(
        mode="original"
    )
    before = deepcopy(original.model_dump(mode="json"))
    converted = adapt_ambibox_catalog(original)
    source, charger = original.sources[0], original.sources[0].chargers[0]
    assert converted.connections[0].id == f"ambibox:broker:{source.id}"
    assert converted.devices[0].id == f"ambibox:charger:{charger.id}"
    assert converted.streams[0].id == f"ambibox:sensor:{charger.id}:temperature"
    assert converted.groups[0].id == f"ambibox:group:{charger.id}"
    assert converted.streams[0].topic == charger.sensors[0].upstream_topic
    assert converted.streams[0].policy.mode == "original"
    assert converted.connections[0].host == source.host
    assert original.model_dump(mode="json") == before


@pytest.mark.asyncio
async def test_structure_saves_survive_reopen_and_never_rewrite_active_collection(
    database,
):
    legacy = catalog("off").model_dump(mode="json")
    with Session(database) as session:
        session.add(
            CollectionConfiguration(
                id=1,
                revision=7,
                document=legacy,
                ingress_status={"status": "disabled"},
                collection_status={"status": "paused"},
                updated_by="operator@example.com",
            )
        )
        session.commit()
        service = system_service.SystemService(AsyncSessionAdapter(session))
        first = await service.save(
            SystemChange(expected_revision=0, document=document()),
            actor="admin@example.com",
        )
        assert first.revision == 1
        assert first.storage_origin == "saved"
        session.commit()
    with Session(database) as session:
        service = system_service.SystemService(AsyncSessionAdapter(session))
        restored = await service.read()
        assert restored.document.model_dump(
            exclude={"streams"}
        ) == document().model_dump(exclude={"streams"})
        assert restored.document.streams[0].policy.mode == "off"
        assert restored.updated_by == "admin@example.com"
        changed = restored.document.model_copy(deep=True)
        changed.connections[0].host = "new.example.com"
        changed.streams[0].label = "Air temperature"
        changed.streams[0].topic = "sensors/office/temperature"
        changed.streams[0].device_id = None
        changed.groups[0].color = "#abcdef"
        saved = await service.save(
            SystemChange(expected_revision=1, document=changed),
            actor="other-admin@example.com",
        )
        assert saved.revision == 2
        session.commit()
    with Session(database) as session:
        service = system_service.SystemService(AsyncSessionAdapter(session))
        restored = await service.read()
        assert restored.revision == 2
        assert restored.document.connections[0].host == "new.example.com"
        assert restored.document.streams[0].topic == "sensors/office/temperature"
        assert restored.document.groups[0].color == "#abcdef"
        unchanged = session.get(CollectionConfiguration, 1)
        assert unchanged.revision == 7 and unchanged.document == legacy
        assert unchanged.collection_status == {"status": "paused"}
        assert len(list(session.scalars(select(SystemRevision)))) == 2
        assert list(session.scalars(select(CollectionRevision))) == []


@pytest.mark.asyncio
async def test_stale_edits_fail_and_noop_does_not_bump_revision(database):
    with Session(database) as session:
        service = system_service.SystemService(AsyncSessionAdapter(session))
        first = await service.save(
            SystemChange(expected_revision=0, document=document()),
            actor="admin@example.com",
        )
        session.commit()
        identical = await service.save(
            SystemChange(expected_revision=first.revision, document=document()),
            actor="admin@example.com",
        )
        assert identical.revision == first.revision
        with pytest.raises(ConflictError):
            await service.save(
                SystemChange(expected_revision=0, document=document()),
                actor="admin@example.com",
            )
        assert session.get(SystemConfiguration, 1).revision == 1
        assert len(list(session.scalars(select(SystemRevision)))) == 1


def test_routes_enforce_current_database_admin_role_and_member_reads(monkeypatch):
    app = FastAPI()
    app.include_router(system_api.router)
    member = User(email="member@example.com", role=RoleEnum.user)
    app.dependency_overrides[current_member] = lambda: member
    app.dependency_overrides[get_db_async] = lambda: AsyncMock()
    read = AsyncMock(return_value={})
    monkeypatch.setattr(system_service.SystemService, "save", read)
    with TestClient(app) as client:
        denied = client.put(
            "/system",
            json={
                "expected_revision": 0,
                "document": document().model_dump(mode="json"),
            },
        )
        assert denied.status_code == 403
        assert read.await_count == 0


def test_members_can_read_and_admins_can_save_with_current_permissions(monkeypatch):
    app = FastAPI()
    app.include_router(system_api.router)
    member = User(email="member@example.com", role=RoleEnum.user)
    app.dependency_overrides[current_member] = lambda: member
    app.dependency_overrides[get_db_async] = lambda: AsyncMock()
    snapshot = SystemSnapshot(revision=1, document=document(), storage_origin="saved")
    read = AsyncMock(return_value=snapshot)
    save = AsyncMock(return_value=snapshot)
    monkeypatch.setattr(system_service.SystemService, "read", read)
    monkeypatch.setattr(system_service.SystemService, "save", save)
    with TestClient(app) as client:
        result = client.get("/system")
        assert result.status_code == 200
        assert result.json()["can_edit"] is False
        member.role = RoleEnum.admin
        result = client.put(
            "/system",
            json={
                "expected_revision": 1,
                "document": document().model_dump(mode="json"),
            },
        )
        assert result.status_code == 200
        assert result.json()["can_edit"] is True
        assert save.await_args.kwargs["actor"] == "member@example.com"


@pytest.mark.asyncio
async def test_gateway_forwards_revision_document_and_authorization(monkeypatch):
    request = AsyncMock(return_value={"revision": 1})
    monkeypatch.setattr(gateway_system.tactic, "request", request)
    change = SystemChange(expected_revision=0, document=document())
    result = await gateway_system.save_system(change, "Bearer test-token")
    assert result == {"revision": 1}
    request.assert_awaited_once_with(
        "PUT",
        "/api/v1/system",
        json_data=change.model_dump(mode="json"),
        headers={"Authorization": "Bearer test-token"},
    )
