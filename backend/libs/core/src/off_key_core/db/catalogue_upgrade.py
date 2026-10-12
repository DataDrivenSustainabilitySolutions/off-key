"""One-time v1 catalogue conversion for migration 005; never used at runtime.

The old configuration tables remain as an archive. Only captured measurement
history and latest-value caches are discarded by the accompanying SQL migration.
"""

from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as upsert

from ..schemas.collection_policy import CollectionPolicy
from ..schemas.system import SystemDocument
from ..schemas.system_collection import (
    ReadingBinding,
    SystemCollectionDefinition,
    build_bindings,
)
from .catalogue_v1 import adapt_ambibox_catalog, legacy_stream_id
from .catalogue_v1_models import AmbiboxCatalog
from .models import (
    Charger,
    CollectionBinding,
    CollectionConfiguration,
    DeploymentMaintenance,
    MonitoringService,
    MqttTopic,
)
from .system import SystemCollectionConfiguration, SystemConfiguration, SystemRevision


def _topic(value):
    if isinstance(value, list):
        return [_topic(item) for item in value]
    if value == "device/#":
        return "telemetry/#"
    if isinstance(value, str) and value.startswith("device/evCharger/"):
        return "telemetry/" + value.removeprefix("device/evCharger/")
    return value


def upgrade_topics(value):
    """Rewrite topic fields only; names and all other configuration stay intact."""
    if isinstance(value, str):
        return _topic(value)
    if isinstance(value, list):
        return [
            upgrade_topics(item) if isinstance(item, dict) else item for item in value
        ]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in {"mqtt_topics", "mqtt_topic", "topic"}:
                result[key] = _topic(item)
            elif isinstance(item, (dict, list)):
                result[key] = upgrade_topics(item)
            else:
                result[key] = item
        return result
    return value


def convert_definition(document, legacy, active=None):
    """Carry stable bindings and explicit policies into the new topic contract."""
    bindings = build_bindings(document, active.bindings if active else None)
    old = {
        legacy_stream_id(stream.charger_id, stream.sensor.key): stream
        for stream in legacy.streams()
    }
    policies = (
        {
            stream.id: stream.policy or active.document.default_policy
            for stream in active.document.streams
        }
        if active
        else {}
    )
    result = document.model_copy(deep=True)
    result.default_policy = CollectionPolicy()
    for stream in result.streams:
        if active is None and (previous := old.get(stream.id)) is not None:
            bindings[stream.id] = ReadingBinding(
                entity_id=previous.charger_id,
                telemetry_key=previous.sensor.key,
                accepted_topic=f"telemetry/{previous.charger_id}/{previous.sensor.key}",
                device_id=stream.device_id,
            )
            stream.policy = previous.policy
        elif active is not None:
            stream.policy = policies.get(stream.id, CollectionPolicy())
        else:
            stream.policy = CollectionPolicy()
        binding = bindings[stream.id]
        binding.accepted_topic = (
            f"telemetry/{binding.entity_id}/{binding.telemetry_key}"
        )
    return SystemCollectionDefinition(
        document=result,
        bindings=bindings,
        generation=uuid4().hex,
    )


def upgrade_saved_catalogue(connection):
    legacy_row = (
        connection.execute(select(CollectionConfiguration.__table__)).mappings().first()
    )
    saved = connection.execute(select(SystemConfiguration.__table__)).mappings().first()
    runtime = (
        connection.execute(select(SystemCollectionConfiguration.__table__))
        .mappings()
        .first()
    )
    legacy = (
        AmbiboxCatalog.model_validate(legacy_row["document"])
        if legacy_row
        else AmbiboxCatalog()
    )
    active = (
        SystemCollectionDefinition.model_validate(runtime["document"])
        if runtime
        else None
    )
    if saved or legacy_row or active:
        _upgrade_catalogue(connection, saved, legacy_row, legacy, runtime, active)
    _upgrade_monitor_topics(connection)


def _upgrade_catalogue(connection, saved, legacy_row, legacy, runtime, active):
    document = (
        SystemDocument.model_validate(saved["document"])
        if saved
        else active.document
        if active
        else adapt_ambibox_catalog(legacy)
    )
    definition = convert_definition(document, legacy, active)
    actor = (saved or runtime or legacy_row)["updated_by"]
    revision = (saved["revision"] if saved else 0) + 1
    data = definition.document.model_dump(mode="json")
    connection.execute(
        upsert(SystemConfiguration)
        .values(
            id=1,
            revision=revision,
            document=data,
            updated_by=actor,
        )
        .on_conflict_do_update(
            index_elements=["id"],
            set_={
                "revision": revision,
                "document": data,
            },
        )
    )
    connection.execute(
        insert(SystemRevision).values(
            revision=revision, document=data, updated_by=actor
        )
    )
    values = {
        "revision": (runtime["revision"] if runtime else 0) + 1,
        "document": definition.model_dump(mode="json"),
        "ingress_status": {},
        "collection_status": {},
        "updated_by": actor,
    }
    connection.execute(
        upsert(SystemCollectionConfiguration)
        .values(id=1, **values)
        .on_conflict_do_update(index_elements=["id"], set_=values)
    )
    devices = {item.id: item.label for item in document.devices}
    brokers = {item.id: item.label for item in document.connections}
    for stream in document.streams:
        binding = definition.bindings[stream.id]
        connection.execute(
            upsert(Charger)
            .values(
                charger_id=binding.entity_id,
                charger_name=devices.get(stream.device_id)
                or brokers[stream.connection_id],
                online=False,
                mqtt_connected=False,
            )
            .on_conflict_do_nothing(index_elements=["charger_id"])
        )
        connection.execute(
            upsert(CollectionBinding)
            .values(
                charger_id=binding.entity_id,
                source_id=stream.connection_id,
                local_id=binding.entity_id,
            )
            .on_conflict_do_update(
                index_elements=["charger_id"],
                set_={
                    "source_id": stream.connection_id,
                    "local_id": binding.entity_id,
                },
            )
        )


def _upgrade_monitor_topics(connection):
    for model, fields in (
        (MonitoringService, ("mqtt_topic", "launch_config")),
        (MqttTopic, ("topic",)),
        (DeploymentMaintenance, ("monitors",)),
    ):
        table = model.__table__
        primary = next(iter(table.primary_key.columns))
        for row in connection.execute(select(table)).mappings():
            changes = {
                field: _topic(row[field])
                if field in {"mqtt_topic", "topic"}
                else upgrade_topics(row[field])
                for field in fields
                if row[field] is not None
            }
            if any(changes[field] != row[field] for field in changes):
                connection.execute(
                    update(table).where(primary == row[primary.name]).values(**changes)
                )
