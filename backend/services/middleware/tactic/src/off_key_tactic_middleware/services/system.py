"""Revisioned system editing; saved configuration never implicitly starts workers."""

from datetime import UTC, datetime

from off_key_core.db.collection import lock_collection_configuration
from off_key_core.db.collection_runtime import read_collection_runtime
from off_key_core.db.maintenance import require_application_writes
from off_key_core.db.models import CollectionState
from off_key_core.db.retention import read_storage_status
from off_key_core.db.system import SystemConfiguration, SystemRevision
from off_key_core.schemas.collection_rules import SystemCollectionRuleChange
from off_key_core.schemas.storage import StorageStatus
from off_key_core.schemas.system import (
    SystemChange,
    SystemDocument,
    SystemRuntime,
    SystemSnapshot,
)
from off_key_core.schemas.system_collection import SystemCollectionChange
from off_key_core.utils.collection_rules import CollectionRuleResolver
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
        runtime.collection_rules = [
            rule.model_dump(mode="json") for rule in definition.rules
        ]
        resolver = CollectionRuleResolver(definition)
        runtime.bindings = {
            item.id: {
                **definition.bindings[item.id].model_dump(mode="json"),
                "connection_id": item.connection_id,
                "policy": item.policy.model_dump(mode="json"),
                "policy_origin": resolver.resolve(item)[1],
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

    async def health(self) -> dict:
        snapshot = await read_collection_runtime(self.session)
        return {
            "revision": snapshot.revision,
            "collection": snapshot.collection,
            "ingress": snapshot.ingress,
        }

    async def storage(self) -> StorageStatus:
        return await read_storage_status(self.session)

    async def require_writes(self) -> None:
        await require_application_writes(self.session)

    async def revisions(self, limit: int = 50) -> list[dict]:
        rows = await self.session.scalars(
            select(SystemRevision).order_by(SystemRevision.revision.desc()).limit(limit)
        )
        return [
            {
                "revision": row.revision,
                "updated_at": row.updated_at.isoformat(),
                "updated_by": row.updated_by,
            }
            for row in rows
        ]

    async def collection_status(self, stream_ids) -> dict:
        """Runtime status narrowed to the requested readings and their brokers."""
        snapshot = await self.read()
        wanted = set(stream_ids)
        runtime = snapshot.runtime
        runtime.bindings = {
            key: value for key, value in runtime.bindings.items() if key in wanted
        }
        connections = {value["connection_id"] for value in runtime.bindings.values()}
        if "sources" in runtime.ingress:
            runtime.ingress["sources"] = {
                key: value
                for key, value in runtime.ingress["sources"].items()
                if key in connections
            }
        if "readings" in runtime.ingress:
            runtime.ingress["readings"] = {
                key: value
                for key, value in runtime.ingress["readings"].items()
                if key in runtime.bindings
            }
        runtime.latest_readings = await self.latest_readings(runtime.bindings)
        return {
            "revision": snapshot.revision,
            "runtime": runtime.model_dump(mode="json"),
        }

    async def preview_collection(
        self, change: SystemCollectionChange | SystemCollectionRuleChange
    ):
        _, preview = await SystemCollectionService(self.session).prepare(
            await self.read(), change
        )
        return preview

    async def save(self, change: SystemChange, *, actor: str) -> SystemSnapshot:
        # Existing maintenance gating and the same advisory lock serialize all
        # system saves, including the first insert when there is no row to lock.
        revision = await self._locked_revision(change.expected_revision)
        normalized = await SystemCollectionService(self.session).sync_structure(
            change.document, actor=actor, pause_monitors=change.pause_affected_monitors
        )
        return await self._write_document(normalized, actor=actor, revision=revision)

    async def apply_collection(
        self,
        change: SystemCollectionChange | SystemCollectionRuleChange,
        *,
        actor: str,
    ) -> SystemSnapshot:
        """Apply reading policies and save the catalogue they were prepared from."""
        await lock_collection_configuration(self.session)
        await require_application_writes(self.session)
        collection = SystemCollectionService(self.session)
        snapshot = await self.read()
        proposed, preview = await collection.prepare(snapshot, change)
        await collection.protect_monitors(
            preview.affected_monitors, change.pause_affected_monitors, proposed
        )
        await collection.persist(proposed, actor=actor)
        revision = await self._locked_revision(snapshot.revision)
        return await self._write_document(
            proposed.document, actor=actor, revision=revision
        )

    async def _locked_revision(self, expected: int) -> int:
        await lock_collection_configuration(self.session)
        await require_application_writes(self.session)
        row = await self._locked_row()
        revision = row.revision if row is not None else 0
        if revision != expected:
            raise ConflictError(
                "The saved system changed. Reload it before saving edits."
            )
        return revision

    async def _locked_row(self) -> SystemConfiguration | None:
        return await self.session.scalar(
            select(SystemConfiguration)
            .where(SystemConfiguration.id == 1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def _write_document(
        self, normalized: SystemDocument, *, actor: str, revision: int
    ) -> SystemSnapshot:
        # Monitor stops may have ended the preparation transaction to wait on
        # Docker. Re-read under the reacquired catalogue lock before applying.
        row = await self._locked_row()
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
