"""Tests for db-sync schema initialization ordering."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from off_key_db_sync.service import SyncService


@pytest.mark.asyncio
async def test_initialize_database_migrates_anomalies_before_create_all():
    service = SyncService()
    call_order: list[str] = []

    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.run_sync = AsyncMock(
        side_effect=lambda *_args, **_kwargs: call_order.append("create_all")
    )

    async def _record_anomaly_migration(_conn):
        call_order.append("migrate_anomaly_identity")

    async def _record_registry_migration(_conn):
        call_order.append("migrate_model_registry")

    service._migrate_anomaly_identity = AsyncMock(side_effect=_record_anomaly_migration)
    service._migrate_model_registry_family = AsyncMock(
        side_effect=_record_registry_migration
    )

    @asynccontextmanager
    async def _begin():
        yield conn

    class _Engine:
        def begin(self):
            return _begin()

    with patch("off_key_db_sync.service.get_async_engine", return_value=_Engine()):
        result = await service._initialize_database()

    assert result is True
    assert service.schema_ready is True
    assert call_order == [
        "migrate_anomaly_identity",
        "migrate_model_registry",
        "create_all",
    ]
