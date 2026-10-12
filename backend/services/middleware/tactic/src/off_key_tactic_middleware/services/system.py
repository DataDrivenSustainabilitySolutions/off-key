"""Revisioned system editing; saved configuration never implicitly starts workers."""

from datetime import UTC, datetime

from off_key_core.db.collection import lock_collection_configuration
from off_key_core.db.maintenance import require_application_writes
from off_key_core.db.models import CollectionState
from off_key_core.db.system import SystemConfiguration, SystemRevision
from off_key_core.schemas.system import (
    SystemChange,
    SystemDocument,
    SystemRuntime,
    SystemSnapshot,
)
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain import ConflictError
from .system_collection import SystemCollectionService


class SystemService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def read(self) -> SystemSnapshot:
        row = await self.session.scalar(
            select(SystemConfiguration).where(SystemConfiguration.id == 1)
        )
        document = row.document if row is not None else SystemDocument()
        runtime = SystemRuntime()
        active, definition = await SystemCollectionService(self.session).current(
            SystemDocument.model_validate(document)
        )
        runtime.collection_revision = active.revision
        runtime.collection = active.collection
        runtime.ingress = active.ingress
        if definition.streams(selected_only=True):
            runtime.mode = "collection"
            runtime.message = "Collection follows explicit reading policies."
        runtime.bindings = {
            item.id: {
                **definition.bindings[item.id].model_dump(mode="json"),
                "connection_id": item.connection_id,
                "policy": item.policy.model_dump(mode="json"),
            }
            for item in definition.document.streams
        }
        if row is not None:
            return SystemSnapshot(
                revision=row.revision,
                document=row.document,
                storage_origin="saved",
                runtime=runtime,
                updated_at=row.updated_at.isoformat(),
                updated_by=row.updated_by,
            )
        return SystemSnapshot(
            revision=0,
            document=SystemDocument(),
            storage_origin="empty",
            runtime=runtime,
        )

    async def save(self, change: SystemChange, *, actor: str) -> SystemSnapshot:
        # Existing maintenance gating and the same advisory lock serialize all
        # system saves, including the first insert when there is no row to lock.
        await lock_collection_configuration(self.session)
        await require_application_writes(self.session)
        row = await self.session.scalar(
            select(SystemConfiguration)
            .where(SystemConfiguration.id == 1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        revision = row.revision if row is not None else 0
        if revision != change.expected_revision:
            raise ConflictError(
                "The saved system changed. Reload it before saving edits."
            )
        normalized = await SystemCollectionService(self.session).sync_structure(
            change.document, actor=actor, pause_monitors=change.pause_affected_monitors
        )
        document = normalized.model_dump(mode="json")
        if row is not None and row.document == document:
            return await self.read()
        revision += 1
        if row is None:
            row = SystemConfiguration(id=1)
            self.session.add(row)
        row.revision = revision
        row.document = document
        row.updated_at = datetime.now(UTC)
        row.updated_by = actor
        self.session.add(
            SystemRevision(revision=revision, document=document, updated_by=actor)
        )
        await self.session.flush()
        return await self.read()

    async def latest_readings(self, bindings):
        if not bindings:
            return {}
        pairs = {
            (item["entity_id"], item["telemetry_key"]) for item in bindings.values()
        }
        states = await self.session.scalars(
            select(CollectionState).where(
                tuple_(CollectionState.charger_id, CollectionState.sensor_key).in_(
                    pairs
                )
            )
        )
        by_key = {(item.charger_id, item.sensor_key): item for item in states}
        return {
            stream_id: {
                "value": state.value,
                "received_at": state.received_at.isoformat(),
                "is_snapshot": state.is_snapshot,
            }
            for stream_id, binding in bindings.items()
            if (state := by_key.get((binding["entity_id"], binding["telemetry_key"])))
            is not None
        }
