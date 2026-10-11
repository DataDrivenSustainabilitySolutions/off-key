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
from off_key_core.schemas.collection import AmbiboxCatalog, CollectionPolicy
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
async def test_main_collection_status_and_history_bindings_survive_the_new_view(
    session,
):
    legacy = catalog()
    legacy.sources[0].chargers[0].policy = CollectionPolicy(mode="original")
    source = legacy.sources[0]
    session.add(
        CollectionConfiguration(
            id=1,
            revision=7,
            document=legacy.model_dump(mode="json"),
            updated_by="operator",
            collection_status={"revision": 7, "status": "applied"},
            ingress_status={
                "revision": 7,
                "status": "applied",
                "sources": {
                    str(source.id): {"status": "connected", "configured": True},
                },
            },
        )
    )
    await session.flush()
    snapshot = await SystemService(session).read()
    connection = snapshot.document.connections[0]
    assert snapshot.runtime.ingress["sources"][connection.id]["state"] == "connected"
    assert snapshot.runtime.collection["revision"] == 7
    binding = next(iter(snapshot.runtime.bindings.values()))
    original = legacy.streams()[0]
    assert binding["entity_id"] == original.charger_id
    assert binding["telemetry_key"] == original.sensor.key
    assert binding["policy"]["mode"] == "original"
    row = session.session.get(CollectionConfiguration, 1)
    assert str(source.id) in row.ingress_status["sources"]
    assert session.session.get(SystemCollectionConfiguration, 1) is None


async def main_recorded_catalogue(session):
    legacy = catalog()
    legacy.sources[0].chargers[0].policy = CollectionPolicy(mode="original")
    session.add(
        CollectionConfiguration(
            id=1,
            revision=7,
            document=legacy.model_dump(mode="json"),
            updated_by="operator",
        )
    )
    await session.flush()
    return await SystemService(session).read()


@pytest.mark.asyncio
async def test_renaming_main_inputs_keeps_the_existing_collection_route(session):
    original = await main_recorded_catalogue(session)
    renamed = original.document.model_copy(deep=True)
    renamed.streams[0].label = "Renamed input"
    saved = await SystemService(session).save(
        SystemChange(expected_revision=0, document=renamed), actor="test@example.com"
    )
    assert saved.document.streams[0].label == "Renamed input"
    assert saved.runtime.bindings == original.runtime.bindings
    assert session.session.get(SystemCollectionConfiguration, 1) is None
    assert session.session.get(CollectionConfiguration, 1).revision == 7


@pytest.mark.asyncio
async def test_removing_a_main_recorded_input_stops_its_hidden_collection(session):
    original = await main_recorded_catalogue(session)
    edited = original.document.model_copy(deep=True)
    edited.streams = []
    edited.groups = []
    await SystemService(session).save(
        SystemChange(expected_revision=0, document=edited), actor="test@example.com"
    )
    runtime = await read_collection_runtime(session)
    assert isinstance(runtime.catalog, SystemCollectionDefinition)
    assert runtime.catalog.streams(selected_only=True) == []
    # The archived main configuration is retained, but no longer drives admission.
    assert session.session.get(CollectionConfiguration, 1).revision == 7
    assert session.session.get(SystemCollectionConfiguration, 1).revision == 1


@pytest.mark.asyncio
async def test_main_monitor_inputs_are_protected_before_structure_handover(session):
    original = await main_recorded_catalogue(session)
    topic = next(iter(original.runtime.bindings.values()))["accepted_topic"]
    session.add(
        MonitoringService(
            id="main-monitor",
            container_name="main-monitor",
            mqtt_topic=[topic],
            status=True,
        )
    )
    await session.flush()
    edited = original.document.model_copy(deep=True)
    edited.streams = []
    edited.groups = []
    with pytest.raises(ConflictError, match="running monitors"):
        await SystemService(session).save(
            SystemChange(expected_revision=0, document=edited), actor="test@example.com"
        )
    assert session.session.get(SystemConfiguration, 1) is None
    assert session.session.get(SystemCollectionConfiguration, 1) is None
    assert session.session.get(MonitoringService, "main-monitor").status is True


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
    assert session.session.get(SystemCollectionConfiguration, 1) is None
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
        document=doc, bindings=build_bindings(doc, AmbiboxCatalog()), generation="test"
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


def test_generic_monitoring_contract_and_legacy_history_binding_are_both_valid():
    definition = runtime_definition()
    stream = definition.streams()[0]
    parsed = TopicMetadataExtractor().extract(stream.accepted_topic)
    assert parsed.charger_id == stream.charger_id
    assert parsed.telemetry_type == stream.key
    assert normalize_static_monitoring_topics([stream.accepted_topic]) == [
        stream.accepted_topic
    ]
    legacy = catalog()
    from off_key_core.schemas.system_adapter import adapt_ambibox_catalog

    doc = adapt_ambibox_catalog(legacy)
    binding = build_bindings(doc, legacy)[doc.streams[0].id]
    assert binding.entity_id == legacy.streams()[0].charger_id
    assert binding.accepted_topic == legacy.streams()[0].accepted_topic


def test_duplicate_generic_aliases_cannot_publish_twice_to_one_legacy_binding():
    from off_key_core.schemas.system_adapter import adapt_ambibox_catalog

    legacy = catalog()
    doc = adapt_ambibox_catalog(legacy)
    original = doc.streams[0]
    alias = original.model_copy(update={"id": "alias"})
    doc.streams.append(alias)
    bindings = build_bindings(doc, legacy)
    assert bindings[original.id].accepted_topic != bindings[alias.id].accepted_topic


def test_reimport_after_removing_a_reading_restores_its_main_history_identity():
    from off_key_core.schemas.system_adapter import adapt_ambibox_catalog

    legacy = catalog()
    saved = adapt_ambibox_catalog(legacy)
    original = build_bindings(saved, legacy)
    removed = saved.model_copy(deep=True)
    removed.streams = []
    remaining = build_bindings(removed, legacy, original)

    restored = build_bindings(saved, legacy, remaining)
    assert restored == original
    assert (
        next(iter(restored.values())).accepted_topic
        == legacy.streams()[0].accepted_topic
    )


def test_reimport_does_not_reuse_history_already_bound_to_an_existing_reading():
    from off_key_core.schemas.system_adapter import adapt_ambibox_catalog

    legacy = catalog()
    saved = adapt_ambibox_catalog(legacy)
    original = build_bindings(saved, legacy)
    reading = saved.streams[0]
    changed = saved.model_copy(deep=True)
    changed.streams[0].topic = "another/input"
    changed.streams.append(reading.model_copy(update={"id": "new-reading"}))

    bindings = build_bindings(changed, legacy, original)
    assert bindings[reading.id] == original[reading.id]
    assert bindings["new-reading"].accepted_topic != original[reading.id].accepted_topic
