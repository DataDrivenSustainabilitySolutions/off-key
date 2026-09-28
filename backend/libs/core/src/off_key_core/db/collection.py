"""Persisted collection configuration shared by the control and ingestion services."""

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas.collection import AmbiboxCatalog, CatalogSnapshot
from .models import CollectionConfiguration

COLLECTION_CONFIGURATION_LOCK = 73128001
COLLECTION_INGRESS_LOCK = 73128002
COLLECTION_PROXY_LOCK = 73128003


async def lock_collection_configuration(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": COLLECTION_CONFIGURATION_LOCK},
    )


async def read_collection_configuration(session: AsyncSession) -> CatalogSnapshot:
    row = await session.scalar(
        select(CollectionConfiguration).where(CollectionConfiguration.id == 1)
    )
    if row is None:
        return CatalogSnapshot(revision=0, catalog=AmbiboxCatalog())
    return CatalogSnapshot(
        revision=row.revision,
        catalog=AmbiboxCatalog.model_validate(row.document),
        ingress=row.ingress_status,
        collection=row.collection_status,
        updated_at=row.updated_at.isoformat(),
        updated_by=row.updated_by,
    )
