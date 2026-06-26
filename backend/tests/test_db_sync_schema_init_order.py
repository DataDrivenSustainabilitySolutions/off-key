"""Tests for db-sync schema initialization ordering."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from off_key_core.db.models import MonitoringService
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

    async def _record_value_type_migration(_conn):
        call_order.append("migrate_anomaly_value_type")

    async def _record_sensor_set_migration(_conn):
        call_order.append("migrate_anomaly_sensor_set")

    async def _record_service_status_migration(_conn):
        call_order.append("migrate_service_operational_status")

    async def _record_registry_migration(_conn):
        call_order.append("migrate_model_registry")

    service._migrate_anomaly_identity = AsyncMock(side_effect=_record_anomaly_migration)
    service._migrate_anomaly_value_type = AsyncMock(
        side_effect=_record_value_type_migration
    )
    service._migrate_anomaly_sensor_set = AsyncMock(
        side_effect=_record_sensor_set_migration
    )
    service._migrate_service_operational_status = AsyncMock(
        side_effect=_record_service_status_migration
    )
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
        "migrate_anomaly_value_type",
        "migrate_anomaly_sensor_set",
        "migrate_service_operational_status",
        "migrate_model_registry",
        "create_all",
    ]


@pytest.mark.asyncio
async def test_ensure_anomaly_identity_trigger_is_created_idempotently():
    service = SyncService()
    conn = AsyncMock()
    conn.execute = AsyncMock()

    await service._ensure_anomaly_identity_trigger(conn)

    executed_sql = " ".join(
        str(call.args[0]) for call in conn.execute.await_args_list if call.args
    )
    assert "CREATE OR REPLACE FUNCTION off_key_sync_anomaly_identity()" in executed_sql
    assert "CREATE OR REPLACE TRIGGER trg_anomaly_identity_sync" in executed_sql


@pytest.mark.asyncio
async def test_migrate_anomaly_value_type_backfills_static_conformal_rows():
    service = SyncService()
    conn = AsyncMock()
    conn.scalar = AsyncMock(side_effect=[True, True])
    conn.execute = AsyncMock()

    await service._migrate_anomaly_value_type(conn)

    executed_sql = " ".join(
        str(call.args[0]) for call in conn.execute.await_args_list if call.args
    )
    assert "SET value_type = 'conformal_pvalue'" in executed_sql
    assert "ml_conformal_static_multivariate" in executed_sql
    assert "ml_conformal_static_univariate" in executed_sql


@pytest.mark.asyncio
async def test_migrate_anomaly_sensor_set_adds_column_and_backfills_univariate():
    service = SyncService()
    conn = AsyncMock()
    conn.scalar = AsyncMock(side_effect=[True, False])
    conn.execute = AsyncMock()

    await service._migrate_anomaly_sensor_set(conn)

    executed_sql = " ".join(
        str(call.args[0]) for call in conn.execute.await_args_list if call.args
    )
    assert "ALTER TABLE anomalies ADD COLUMN sensor_set JSONB" in executed_sql
    assert "jsonb_build_array(telemetry_type)" in executed_sql
    assert "telemetry_type <> '__multivariate__'" in executed_sql


@pytest.mark.asyncio
async def test_migrate_service_operational_status_adds_and_backfills_columns():
    service = SyncService()
    conn = AsyncMock()
    conn.scalar = AsyncMock(side_effect=[True, False, False, False])
    conn.execute = AsyncMock()

    await service._migrate_service_operational_status(conn)

    executed_sql = " ".join(
        str(call.args[0]) for call in conn.execute.await_args_list if call.args
    )
    assert "ALTER TABLE services ADD COLUMN operational_stage TEXT" in executed_sql
    assert "ALTER TABLE services ADD COLUMN operational_status JSONB" in executed_sql
    assert (
        "ALTER TABLE services ADD COLUMN operational_updated_at TIMESTAMPTZ"
        in executed_sql
    )
    assert "WHEN status IS TRUE THEN 'starting'" in executed_sql
    assert "'processed_message_count', 0" in executed_sql
    assert "ALTER COLUMN operational_stage SET NOT NULL" in executed_sql


def test_monitoring_service_operational_status_uses_postgresql_jsonb():
    ddl = str(
        CreateTable(MonitoringService.__table__).compile(dialect=postgresql.dialect())
    )

    assert "operational_status JSONB" in ddl
