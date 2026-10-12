"""Persisted collection configuration shared by the control and ingestion services."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

COLLECTION_CONFIGURATION_LOCK = 73128001
COLLECTION_PROXY_LOCK = 73128003


async def lock_collection_configuration(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": COLLECTION_CONFIGURATION_LOCK},
    )
