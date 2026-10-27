"""Generic opt-in admission, stable history identities and monitor protection."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from off_key_core.db.collection_runtime import read_collection_runtime
from off_key_core.db.models import (
    Charger,
    CollectionBinding,
    CollectionConfiguration,
    MonitoringPipeline,
    MonitoringService,
    PipelineActivation,
    PipelineRevision,
    PipelineRun,
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
from off_key_tactic_middleware import bootstrap_demo_catalogue
from off_key_tactic_middleware.config.system_live import SystemLiveSettings
from off_key_tactic_middleware.domain import ConflictError
from off_key_tactic_middleware.services.catalogue import system as system_module
from off_key_tactic_middleware.services.catalogue import (
    system_collection as collection_module,
)
from off_key_tactic_middleware.services.catalogue.system import SystemService
from off_key_tactic_middleware.services.catalogue.system_collection import (
    SystemCollectionService,
)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from tests.support.collection import catalog
from tests.support.system_document import (
    AsyncSessionAdapter,
    create_sqlite_tables,
    document,
)


@pytest.fixture
def session(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'collection.db'}")
    create_sqlite_tables(
        engine,
        [
            SystemConfiguration.__table__,
            SystemRevision.__table__,
            SystemCollectionConfiguration.__table__,
            CollectionConfiguration.__table__,
            Charger.__table__,
            CollectionBinding.__table__,
            MonitoringService.__table__,
            MonitoringPipeline.__table__,
            PipelineRevision.__table__,
            PipelineRun.__table__,
            PipelineActivation.__table__,
        ],
    )
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
    snapshot = await SystemService(session).apply_collection(
        change(snapshot), actor="test@example.com"
    )
    assert snapshot.document.default_policy.mode == "off"
    assert snapshot.document.streams[0].policy.mode == "sample"
    runtime = await read_collection_runtime(session)
    assert isinstance(runtime.catalog, SystemCollectionDefinition)
    assert len(runtime.catalog.streams(selected_only=True)) == 1
    assert len(list(session.session.scalars(select(Charger)))) == 1


@pytest.mark.asyncio
async def test_collection_apply_writes_one_catalogue_and_collection_revision(session):
    saved = await SystemService(session).save(
        SystemChange(expected_revision=0, document=document()), actor="test@example.com"
    )
    collection_revision = saved.runtime.collection_revision
    applied = await SystemService(session).apply_collection(
        change(saved), actor="admin@example.com"
    )
    assert applied.revision == saved.revision + 1
    assert applied.updated_by == "admin@example.com"
    assert applied.runtime.collection_revision == collection_revision + 1
    revisions = list(session.session.scalars(select(SystemRevision)))
    assert [item.revision for item in revisions] == [1, 2]
    assert revisions[-1].document == applied.document.model_dump(mode="json")
    row = session.session.get(SystemCollectionConfiguration, 1)
    assert row.updated_by == "admin@example.com"
    assert row.ingress_status == {} and row.collection_status == {}
    # The same policy again changes nothing: no catalogue or collection revision.
    again = await SystemService(session).apply_collection(
        change(applied), actor="admin@example.com"
    )
    assert again.revision == applied.revision
    assert again.runtime.collection_revision == applied.runtime.collection_revision
    assert len(list(session.session.scalars(select(SystemRevision)))) == 2


@pytest.mark.asyncio
async def test_new_imported_readings_stay_off_and_renames_keep_runtime_generation(
    session,
):
    snapshot = await SystemService(session).save(
        SystemChange(expected_revision=0, document=document()), actor="test@example.com"
    )
    snapshot = await SystemService(session).apply_collection(
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
    assert (
        row.revision == revision + 1
    )  # Admission metadata changed; active inputs did not.
    assert row.document["generation"] == generation


@pytest.mark.asyncio
async def test_stale_policy_change_cannot_overwrite_a_newer_decision(session):
    snapshot = await SystemService(session).save(
        SystemChange(expected_revision=0, document=document()), actor="test@example.com"
    )
    original = change(snapshot)
    await SystemService(session).apply_collection(original, actor="test@example.com")
    with pytest.raises(ConflictError, match="changed"):
        await SystemService(session).apply_collection(
            original, actor="test@example.com"
        )


@pytest.mark.asyncio
async def test_collection_and_structure_changes_protect_active_monitor_inputs(session):
    snapshot = await SystemService(session).save(
        SystemChange(expected_revision=0, document=document()), actor="test@example.com"
    )
    snapshot = await SystemService(session).apply_collection(
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
        await SystemService(session).apply_collection(
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


@pytest.mark.asyncio
async def test_scope_rules_survive_structure_edits_and_admit_only_approved_additions(
    session,
):
    from off_key_core.schemas.collection_rules import (
        CollectionRuleEdit,
        CollectionRuleScope,
        SystemCollectionRuleChange,
    )

    snapshot = await SystemService(session).save(
        SystemChange(expected_revision=0, document=document()), actor="test@example.com"
    )
    broker = CollectionRuleScope(kind="broker", connection_id="broker-1")

    async def apply(snapshot, edit):
        return await SystemService(session).apply_collection(
            SystemCollectionRuleChange(
                expected_revision=snapshot.revision,
                expected_collection_revision=snapshot.runtime.collection_revision,
                rule_changes=[edit],
            ),
            actor="test@example.com",
        )

    snapshot = await apply(
        snapshot,
        CollectionRuleEdit(scope=broker, policy=CollectionPolicy(mode="original")),
    )
    binding = snapshot.runtime.bindings["temperature-1"]
    generation = (await read_collection_runtime(session)).catalog.generation
    next_doc = snapshot.document.model_copy(deep=True)
    next_doc.streams.append(
        next_doc.streams[0].model_copy(
            update={"id": "humidity", "payload_pointer": "/humidity"}
        )
    )
    snapshot = await SystemService(session).save(
        SystemChange(expected_revision=snapshot.revision, document=next_doc),
        actor="test@example.com",
    )
    assert snapshot.runtime.bindings["temperature-1"] == binding
    assert snapshot.runtime.bindings["humidity"]["policy"]["mode"] == "off"
    assert snapshot.runtime.bindings["humidity"]["policy_origin"]["needs_review"]
    assert (await read_collection_runtime(session)).catalog.generation == generation
    snapshot = await apply(
        snapshot,
        CollectionRuleEdit(
            scope=broker, policy=CollectionPolicy(mode="sample", interval_seconds=7)
        ),
    )
    assert snapshot.runtime.bindings["humidity"]["policy"]["mode"] == "off"
    snapshot = await apply(
        snapshot, CollectionRuleEdit(scope=broker, operation="include")
    )
    assert snapshot.runtime.bindings["humidity"]["policy"]["mode"] == "sample"
    assert snapshot.runtime.bindings["humidity"]["policy_origin"]["inherited"]
    snapshot = await apply(
        snapshot,
        CollectionRuleEdit(
            scope=broker,
            policy=CollectionPolicy(mode="original"),
            include_future_readings=True,
        ),
    )
    next_doc = snapshot.document.model_copy(deep=True)
    next_doc.streams.append(
        next_doc.streams[0].model_copy(
            update={"id": "voltage", "payload_pointer": "/voltage"}
        )
    )
    snapshot = await SystemService(session).save(
        SystemChange(expected_revision=snapshot.revision, document=next_doc),
        actor="test@example.com",
    )
    assert snapshot.runtime.bindings["voltage"]["policy"]["mode"] == "original"
    persisted = await read_collection_runtime(session)
    assert (
        persisted.catalog.rules
        and persisted.catalog.bindings["temperature-1"].entity_id
        == binding["entity_id"]
    )


@pytest.mark.asyncio
async def test_future_rule_metadata_advances_revision_without_restarting_ingestion(
    session,
):
    from off_key_core.schemas.collection_rules import (
        CollectionRuleEdit,
        CollectionRuleScope,
        SystemCollectionRuleChange,
    )

    snapshot = await SystemService(session).save(
        SystemChange(expected_revision=0, document=document()), actor="test@example.com"
    )
    service = SystemService(session)

    def request(snapshot, future):
        return SystemCollectionRuleChange(
            expected_revision=snapshot.revision,
            expected_collection_revision=snapshot.runtime.collection_revision,
            rule_changes=[
                CollectionRuleEdit(
                    scope=CollectionRuleScope(kind="broker", connection_id="broker-1"),
                    policy=CollectionPolicy(mode="off"),
                    include_future_readings=future,
                )
            ],
        )

    first = await service.apply_collection(
        request(snapshot, False), actor="test@example.com"
    )
    generation = (await read_collection_runtime(session)).catalog.generation
    second = await service.apply_collection(
        request(first, True), actor="test@example.com"
    )
    assert second.runtime.collection_revision == first.runtime.collection_revision + 1
    assert (await read_collection_runtime(session)).catalog.generation == generation
    with pytest.raises(ConflictError):
        await service.apply_collection(request(first, False), actor="test@example.com")


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["include", "inherit"])
async def test_moving_an_admitted_reading_requires_review_and_keeps_overrides(
    session, operation
):
    from off_key_core.schemas.collection_rules import (
        CollectionRuleEdit,
        CollectionRuleScope,
        SystemCollectionRuleChange,
    )

    service = SystemService(session)
    snapshot = await service.save(
        SystemChange(expected_revision=0, document=document()), actor="test@example.com"
    )
    broker = CollectionRuleScope(kind="broker", connection_id="broker-1")
    humidity = CollectionRuleScope(
        kind="reading", connection_id="broker-1", reading_id="humidity"
    )

    async def apply(snapshot, edits):
        return await service.apply_collection(
            SystemCollectionRuleChange(
                expected_revision=snapshot.revision,
                expected_collection_revision=snapshot.runtime.collection_revision,
                rule_changes=edits,
            ),
            actor="test@example.com",
        )

    snapshot = await apply(
        snapshot,
        [CollectionRuleEdit(scope=broker, policy=CollectionPolicy(mode="original"))],
    )
    next_doc = snapshot.document.model_copy(deep=True)
    next_doc.streams.append(
        next_doc.streams[0].model_copy(
            update={"id": "humidity", "payload_pointer": "/humidity"}
        )
    )
    snapshot = await service.save(
        SystemChange(expected_revision=snapshot.revision, document=next_doc),
        actor="test@example.com",
    )
    assert snapshot.runtime.bindings["humidity"]["policy_origin"]["needs_review"]
    snapshot = await apply(
        snapshot,
        [
            CollectionRuleEdit(
                scope=broker if operation == "include" else humidity,
                operation=operation,
            ),
            CollectionRuleEdit(
                scope=CollectionRuleScope(
                    kind="reading",
                    connection_id="broker-1",
                    reading_id="temperature-1",
                ),
                policy=CollectionPolicy(mode="sample", interval_seconds=7),
            ),
        ],
    )
    included = await service.read()
    binding = included.runtime.bindings["humidity"]
    assert binding["policy"]["mode"] == "original"
    next_doc = included.document.model_copy(deep=True)
    next_doc.streams[1].label = "Renamed humidity"
    renamed = await service.save(
        SystemChange(expected_revision=included.revision, document=next_doc),
        actor="test@example.com",
    )
    assert renamed.runtime.bindings["humidity"] == binding
    next_doc = renamed.document.model_copy(deep=True)
    next_doc.streams[0].topic = "elsewhere/temperature"
    next_doc.streams[1].topic = "elsewhere/humidity"
    moved = await service.save(
        SystemChange(expected_revision=renamed.revision, document=next_doc),
        actor="test@example.com",
    )
    moved_binding = moved.runtime.bindings["humidity"]
    assert moved_binding["policy"]["mode"] == "off"
    assert moved_binding["policy_origin"]["needs_review"]
    assert moved_binding["accepted_topic"] == binding["accepted_topic"]
    assert moved.runtime.bindings["temperature-1"]["policy"] == {
        "mode": "sample",
        "interval_seconds": 7,
    }
    assert moved.runtime.collection_revision > renamed.runtime.collection_revision
    assert all(
        rule["scope"] != humidity.model_dump(mode="json")
        for rule in moved.runtime.collection_rules
    )
    with pytest.raises(ConflictError):
        await apply(
            renamed,
            [
                CollectionRuleEdit(
                    scope=humidity,
                    operation="restore",
                    restore_rule=next(
                        rule
                        for rule in renamed.runtime.collection_rules
                        if rule["scope"] == humidity.model_dump(mode="json")
                    ),
                )
            ],
        )
    readmitted = await apply(
        moved, [CollectionRuleEdit(scope=humidity, operation="inherit")]
    )
    assert readmitted.runtime.bindings["humidity"]["policy"]["mode"] == "original"


@pytest.mark.asyncio
async def test_demo_catalogue_loads_once_and_records_every_reading(session):
    loaded = await bootstrap_demo_catalogue.seed(session, document())
    assert loaded == {"status": "loaded", "readings": 1}
    snapshot = await SystemService(session).read()
    assert snapshot.updated_by == bootstrap_demo_catalogue.ACTOR
    assert snapshot.runtime.bindings["temperature-1"]["policy"] == {
        "mode": "sample",
        "interval_seconds": 60,
    }
    # Later deployments keep the administrator's catalogue.
    edited = document()
    edited.label = "Edited by the administrator"
    assert await bootstrap_demo_catalogue.seed(session, edited) == {"status": "kept"}
    assert (await SystemService(session).read()).revision == snapshot.revision
