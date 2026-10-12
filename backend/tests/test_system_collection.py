"""Generic opt-in admission, stable history identities and monitor protection."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from off_key_core.db.collection_runtime import read_collection_runtime
from off_key_core.db.models import (
    Charger,
    CollectionBinding,
    CollectionConfiguration,
    MonitoringService,
)
from off_key_core.db.system import (
    SystemCollectionConfiguration,
    SystemConfiguration,
    SystemRevision,
)
from off_key_core.schemas.collection_policy import CollectionPolicy
from off_key_core.schemas.system import SystemChange
from off_key_core.schemas.system_collection import (
    SystemCollectionChange,
    SystemCollectionDefinition,
    build_bindings,
)
from off_key_core.utils.mqtt_topics import (
    TopicMetadataExtractor,
    normalize_static_monitoring_topics,
)
from off_key_mqtt_proxy.client.models import MQTTMessage
from off_key_mqtt_proxy.collection_buffer import CollectionBuffer
from off_key_tactic_middleware.config.system_live import SystemLiveSettings
from off_key_tactic_middleware.domain import ConflictError
from off_key_tactic_middleware.services import system as system_module
from off_key_tactic_middleware.services import system_collection as collection_module
from off_key_tactic_middleware.services.system import SystemService
from off_key_tactic_middleware.services.system_collection import SystemCollectionService
from sqlalchemy import JSON, MetaData, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from .test_collection import catalog
from .test_system_configuration import AsyncSessionAdapter, document


@pytest.fixture
def session(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'collection.db'}")
    metadata = MetaData()
    for model in (
        SystemConfiguration,
        SystemRevision,
        SystemCollectionConfiguration,
        CollectionConfiguration,
        Charger,
        CollectionBinding,
        MonitoringService,
    ):
        table = model.__table__.to_metadata(metadata)
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()
    metadata.create_all(engine)
    for module in (system_module, collection_module):
        monkeypatch.setattr(module, "lock_collection_configuration", AsyncMock())
        monkeypatch.setattr(module, "require_application_writes", AsyncMock())
    monkeypatch.setattr(
        collection_module,
        "get_system_live_settings",
        lambda: SystemLiveSettings(SYSTEM_LIVE_ALLOWED_HOSTS=["localhost"]),
    )
    with Session(engine) as db:
        yield AsyncSessionAdapter(db)
    engine.dispose()


def change(snapshot, mode="sample", interval=2):
    return SystemCollectionChange(
        expected_revision=snapshot.revision,
        expected_collection_revision=snapshot.runtime.collection_revision,
        stream_ids=["temperature-1"],
        policy=CollectionPolicy(mode=mode, interval_seconds=interval),
    )


@pytest.mark.asyncio
async def test_archived_catalogue_never_drives_runtime(session):
    session.add(
        CollectionConfiguration(
            id=1,
            revision=7,
            document=catalog().model_dump(mode="json"),
            updated_by="operator",
        )
    )
    await session.flush()
    snapshot = await SystemService(session).read()
    assert snapshot.document.streams == []
    assert snapshot.runtime.bindings == {}
    assert snapshot.runtime.collection_revision == 0
    assert snapshot.storage_origin == "empty"


@pytest.mark.asyncio
async def test_metadata_import_never_enables_recording_but_explicit_action_does(
    session,
):
    proposed = document()
    proposed.default_policy.mode = "original"
    proposed.streams[0].policy = CollectionPolicy(mode="original")
    snapshot = await SystemService(session).save(
        SystemChange(expected_revision=0, document=proposed), actor="test@example.com"
    )
    assert session.session.get(SystemCollectionConfiguration, 1) is not None
    assert snapshot.runtime.bindings["temperature-1"]["policy"]["mode"] == "off"
    snapshot = await SystemCollectionService(session).apply(
        change(snapshot), actor="test@example.com"
    )
    assert snapshot.document.default_policy.mode == "off"
    assert snapshot.document.streams[0].policy.mode == "sample"
    runtime = await read_collection_runtime(session)
    assert isinstance(runtime.catalog, SystemCollectionDefinition)
    assert len(runtime.catalog.streams(selected_only=True)) == 1
    assert len(list(session.session.scalars(select(Charger)))) == 1


@pytest.mark.asyncio
async def test_new_imported_readings_stay_off_and_renames_keep_runtime_generation(
    session,
):
    snapshot = await SystemService(session).save(
        SystemChange(expected_revision=0, document=document()), actor="test@example.com"
    )
    snapshot = await SystemCollectionService(session).apply(
        change(snapshot), actor="test@example.com"
    )
    row = session.session.get(SystemCollectionConfiguration, 1)
    generation, revision = row.document["generation"], row.revision
    binding = snapshot.runtime.bindings["temperature-1"]
    imported = snapshot.document.model_copy(deep=True)
    imported.streams[0].label = "Renamed temperature"
    imported.streams.append(
        imported.streams[0].model_copy(
            update={
                "id": "humidity-1",
                "label": "Humidity",
                "payload_pointer": "/readings/humidity",
                "policy": CollectionPolicy(mode="original"),
            }
        )
    )
    result = await SystemService(session).save(
        SystemChange(expected_revision=snapshot.revision, document=imported),
        actor="test@example.com",
    )
    assert result.runtime.bindings["humidity-1"]["policy"]["mode"] == "off"
    assert result.runtime.bindings["temperature-1"] == binding
    assert row.revision == revision and row.document["generation"] == generation


@pytest.mark.asyncio
async def test_stale_policy_change_cannot_overwrite_a_newer_decision(session):
    snapshot = await SystemService(session).save(
        SystemChange(expected_revision=0, document=document()), actor="test@example.com"
    )
    original = change(snapshot)
    await SystemCollectionService(session).apply(original, actor="test@example.com")
    with pytest.raises(ConflictError, match="changed"):
        await SystemCollectionService(session).apply(original, actor="test@example.com")


@pytest.mark.asyncio
async def test_collection_and_structure_changes_protect_active_monitor_inputs(session):
    snapshot = await SystemService(session).save(
        SystemChange(expected_revision=0, document=document()), actor="test@example.com"
    )
    snapshot = await SystemCollectionService(session).apply(
        change(snapshot), actor="test@example.com"
    )
    topic = snapshot.runtime.bindings["temperature-1"]["accepted_topic"]
    session.add(
        MonitoringService(
            id="monitor", container_name="monitor", mqtt_topic=[topic], status=True
        )
    )
    await session.flush()
    proposed, preview = await SystemCollectionService(session).prepare(
        snapshot, change(snapshot, "off")
    )
    assert preview.affected_monitors == [{"id": "monitor", "name": "monitor"}]
    with pytest.raises(ConflictError, match="running monitors"):
        await SystemCollectionService(session).apply(
            change(snapshot, "off"), actor="test@example.com"
        )
    draft = snapshot.document.model_copy(deep=True)
    draft.streams[0].payload_pointer = "/readings/other"
    with pytest.raises(ConflictError, match="running monitors"):
        await SystemService(session).save(
            SystemChange(expected_revision=snapshot.revision, document=draft),
            actor="test@example.com",
        )
    assert proposed.streams(selected_only=True) == []


def runtime_definition():
    doc = document()
    doc.streams[0].policy = CollectionPolicy(mode="sample", interval_seconds=2)
    return SystemCollectionDefinition(
        document=doc, bindings=build_bindings(doc), generation="test"
    )


def incoming(stream, payload, retained=False):
    now = datetime.now(UTC)
    return MQTTMessage(
        topic=stream.ingress_topic,
        payload={
            "payload": payload,
            "received_at": int(now.timestamp() * 1000),
            "upstream_retained": retained,
        },
        timestamp=now,
        retain=False,
        qos=0,
    )


def test_generic_json_pointer_sample_original_off_and_retained_admission():
    definition = runtime_definition()
    stream = definition.streams()[0]
    buffer = CollectionBuffer(original_capacity=2)
    buffer.configure(definition, now=0)
    buffer.receive(incoming(stream, '{"readings":{"temperature":21}}'))
    buffer.receive(incoming(stream, '{"readings":{"temperature":22}}'))
    assert buffer.take(now=1) == []
    sampled = buffer.take(now=2)
    assert len(sampled) == 1 and sampled[0].value == 22
    assert sampled[0].message().topic.startswith("telemetry/entity-")
    buffer.receive(incoming(stream, '{"readings":{"temperature":23}}', retained=True))
    assert buffer.take(now=4)[0].snapshot
    definition.document.streams[0].policy.mode = "original"
    buffer.configure(definition, now=5)
    for value in range(3):
        buffer.receive(
            incoming(stream, '{"readings":{"temperature":' + str(value) + "}}")
        )
    assert [item.value for item in buffer.take(now=5)] == [0, 1]
    assert buffer.metrics()["overload_dropped"] == 1
    definition.document.streams[0].policy.mode = "off"
    buffer.configure(definition, now=6)
    buffer.receive(incoming(stream, '{"readings":{"temperature":99}}'))
    assert buffer.take(now=100) == []


def test_generic_monitoring_contract_rejects_the_old_namespace():
    definition = runtime_definition()
    stream = definition.streams()[0]
    parsed = TopicMetadataExtractor().extract(stream.accepted_topic)
    assert parsed.charger_id == stream.charger_id
    assert parsed.telemetry_type == stream.key
    assert normalize_static_monitoring_topics([stream.accepted_topic]) == [
        stream.accepted_topic
    ]
    assert TopicMetadataExtractor().extract("device/evCharger/old/temperature") is None
    with pytest.raises(ValueError):
        normalize_static_monitoring_topics(["device/evCharger/old/temperature"])


def test_duplicate_inputs_receive_distinct_generic_bindings():
    doc = document()
    doc.streams.append(doc.streams[0].model_copy(update={"id": "alias"}))
    bindings = build_bindings(doc)
    assert len({binding.accepted_topic for binding in bindings.values()}) == 2


def test_reimport_restores_deterministic_generic_identities():
    doc = document()
    original = build_bindings(doc)
    removed = doc.model_copy(deep=True)
    removed.streams = []
    assert build_bindings(doc, build_bindings(removed, original)) == original


def test_saved_bindings_survive_topic_edits_without_matching_other_catalogues():
    doc = document()
    original = build_bindings(doc)
    doc.streams[0].topic = "another/input"
    doc.streams.append(doc.streams[0].model_copy(update={"id": "new-reading"}))
    bindings = build_bindings(doc, original)
    assert bindings[doc.streams[0].id] == original[doc.streams[0].id]
    assert (
        bindings["new-reading"].accepted_topic
        != original[doc.streams[0].id].accepted_topic
    )
