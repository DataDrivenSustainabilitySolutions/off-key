"""Persisted collection configuration shared by the control and ingestion services."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .locks import COLLECTION_CONFIGURATION_LOCK, COLLECTION_PROXY_LOCK

__all__ = [
    "COLLECTION_CONFIGURATION_LOCK",
    "COLLECTION_PROXY_LOCK",
    "lock_collection_configuration",
]


async def lock_collection_configuration(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": COLLECTION_CONFIGURATION_LOCK},
    )
