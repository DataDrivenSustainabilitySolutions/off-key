"""Catalog changes and their effect on active monitoring workloads."""

from datetime import UTC, datetime
from math import ceil

from off_key_core.db.base import get_async_session_local
from off_key_core.db.collection import (
    lock_collection_configuration,
    read_collection_configuration,
)
from off_key_core.db.models import (
    Charger,
    CollectionBinding,
    CollectionConfiguration,
    CollectionRevision,
    MonitoringService,
)
from off_key_core.schemas.collection import (
    AmbiboxCatalog,
    CatalogChange,
    CatalogPreview,
    CatalogSnapshot,
    assign_forward_ports,
)
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config.collection import get_ambibox_settings
from ..domain import ConflictError, InfrastructureError, ValidationError
from .orchestration.radar_workloads import RadarWorkloadManager, get_async_docker
from .radar_status import mark_collection_monitor_stopped


def changed_collection_topics(
    before: AmbiboxCatalog, after: AmbiboxCatalog
) -> set[str]:
    def signatures(catalog: AmbiboxCatalog) -> dict:
        endpoints = {
            str(source.id): (source.host, source.port) for source in catalog.sources
        }
        return {
            stream.accepted_topic: (stream.signature, endpoints[stream.source_id])
            for stream in catalog.streams(selected_only=True)
        }

    previous, proposed = signatures(before), signatures(after)
    return {
        topic
        for topic in previous.keys() | proposed.keys()
        if previous.get(topic) != proposed.get(topic)
    }


class CollectionService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def preview(self, change: CatalogChange) -> CatalogPreview:
        current = await read_collection_configuration(self.session)
        if current.revision != change.expected_revision:
            raise ConflictError("The catalog changed. Reload it before applying edits.")
        settings = get_ambibox_settings()
        for source in change.catalog.sources:
            if not settings.allows_host(source.host):
                raise ValidationError(
                    f"Broker {source.host} is outside the configured AmbiBox network"
                )
        catalog = assign_forward_ports(change.catalog, current.catalog)
        changed_topics = changed_collection_topics(current.catalog, catalog)
        monitors = await self.session.scalars(
            select(MonitoringService).where(MonitoringService.status.is_(True))
        )
        affected = [
            {"id": monitor.id, "name": monitor.container_name}
            for monitor in monitors
            if changed_topics.intersection(monitor.mqtt_topic or [])
        ]
        selected = catalog.streams(selected_only=True)
        numeric = [
            stream for stream in selected if stream.sensor.value_type == "number"
        ]
        return CatalogPreview(
            revision=current.revision,
            catalog=catalog,
            chargers=sum(len(source.chargers) for source in catalog.sources),
            selected_sensors=len(selected),
            sampled_rows_per_day_ceiling=sum(
                ceil(86400 / stream.policy.interval_seconds)
                for stream in numeric
                if stream.policy.mode == "sample"
            ),
            original_rate_sensors=sum(
                stream.policy.mode == "original" for stream in numeric
            ),
            affected_monitors=affected,
        )

    async def apply(self, change: CatalogChange, *, actor: str) -> CatalogSnapshot:
        await lock_collection_configuration(self.session)
        preview = await self.preview(change)
        if preview.affected_monitors and not change.pause_affected_monitors:
            raise ConflictError(
                "This change affects running monitors. Review and pause them first."
            )
        await self._pause_monitors(preview.affected_monitors)
        catalog = preview.catalog
        revision = preview.revision + 1
        document = catalog.model_dump(mode="json")
        await self._update_bindings(catalog)
        statement = insert(CollectionConfiguration).values(
            id=1,
            revision=revision,
            document=document,
            ingress_status={},
            collection_status={},
            updated_at=datetime.now(UTC),
            updated_by=actor,
        )
        await self.session.execute(
            statement.on_conflict_do_update(
                index_elements=[CollectionConfiguration.id],
                set_={
                    "revision": revision,
                    "document": document,
                    "updated_at": statement.excluded.updated_at,
                    "updated_by": actor,
                },
            )
        )
        self.session.add(
            CollectionRevision(revision=revision, document=document, updated_by=actor)
        )
        await self.session.flush()
        # Refresh after SQL upsert even if a previous read populated the identity map.
        self.session.expire_all()
        return await read_collection_configuration(self.session)

    async def _pause_monitors(self, affected: list[dict]) -> None:
        if not affected:
            return
        # The caller holds the catalog lock. Commit stop intent independently:
        # Docker removal cannot be rolled back with a failed catalog transaction.
        sessions = get_async_session_local()
        ids = [item["id"] for item in affected]
        async with sessions.begin() as session:
            await session.execute(
                update(MonitoringService)
                .where(
                    MonitoringService.id.in_(ids), MonitoringService.status.is_(True)
                )
                .values(stop_requested_at=datetime.now(UTC))
            )

        workloads = RadarWorkloadManager(get_async_docker())
        for monitor_id in ids:
            try:
                async with sessions.begin() as session:
                    monitor = await session.get(
                        MonitoringService, monitor_id, with_for_update=True
                    )
                    if monitor is None or monitor.stop_requested_at is None:
                        continue
                    await workloads.remove(monitor.container_id)
                    mark_collection_monitor_stopped(monitor)
            except Exception as exc:
                raise InfrastructureError(
                    "The catalog was not applied. Monitor stops are saved and will "
                    "be retried automatically; retry the catalog change "
                    "after they finish."
                ) from exc
        self.session.expire_all()

    async def _update_bindings(self, catalog: AmbiboxCatalog) -> None:
        old_ids = set(await self.session.scalars(select(CollectionBinding.charger_id)))
        chargers, bindings = [], []
        for source in catalog.sources:
            for charger in source.chargers:
                chargers.append(
                    {
                        "charger_id": str(charger.id),
                        "charger_name": charger.label,
                        "manufacturer_name": "AmbiBox",
                        "online": False,
                        "mqtt_connected": False,
                    }
                )
                bindings.append(
                    {
                        "charger_id": str(charger.id),
                        "source_id": str(source.id),
                        "local_id": charger.local_id,
                    }
                )
        if chargers:
            statement = insert(Charger).values(chargers)
            await self.session.execute(
                statement.on_conflict_do_update(
                    index_elements=[Charger.charger_id],
                    set_={"charger_name": statement.excluded.charger_name},
                )
            )
        await self.session.execute(delete(CollectionBinding))
        if bindings:
            await self.session.execute(insert(CollectionBinding).values(bindings))
        retired = old_ids - {item["charger_id"] for item in chargers}
        if retired:
            await self.session.execute(
                update(Charger)
                .where(Charger.charger_id.in_(retired))
                .values(online=False, mqtt_connected=False)
            )
