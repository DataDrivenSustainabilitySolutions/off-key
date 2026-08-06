"""Tests for db-sync schema initialization ordering."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from off_key_core.db.models import MonitoringEvidence, MonitoringService
from off_key_db_sync.service import SyncService
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable


@pytest.mark.asyncio
async def test_initialize_database_migrates_anomalies_before_create_all():  # noqa: C901
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

    async def _record_evidence_migration(_conn):
        call_order.append("migrate_monitoring_evidence_trackers")

    async def _record_evidence_strategy_migration(_conn):
        call_order.append("migrate_monitoring_evidence_strategy")

    async def _record_evidence_input_timestamp_migration(_conn):
        call_order.append("migrate_monitoring_evidence_input_timestamps")

    async def _record_chart_indexes(_conn):
        call_order.append("ensure_chart_query_indexes")

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
    service._migrate_monitoring_evidence_trackers = AsyncMock(
        side_effect=_record_evidence_migration
    )
    service._migrate_monitoring_evidence_strategy = AsyncMock(
        side_effect=_record_evidence_strategy_migration
    )
    service._migrate_monitoring_evidence_input_timestamps = AsyncMock(
        side_effect=_record_evidence_input_timestamp_migration
    )
    service._ensure_chart_query_indexes = AsyncMock(side_effect=_record_chart_indexes)

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
        "migrate_monitoring_evidence_trackers",
        "migrate_monitoring_evidence_strategy",
        "migrate_monitoring_evidence_input_timestamps",
        "create_all",
        "ensure_chart_query_indexes",
    ]


@pytest.mark.asyncio
async def test_ensure_chart_query_indexes_are_idempotent():
    service = SyncService()
    conn = AsyncMock()
    conn.execute = AsyncMock()

    await service._ensure_chart_query_indexes(conn)

    executed_sql = " ".join(
        str(call.args[0]) for call in conn.execute.await_args_list if call.args
    )
    assert "CREATE INDEX IF NOT EXISTS" in executed_sql
    assert "ON telemetry (charger_id, type, timestamp DESC)" in executed_sql
    assert "ON telemetry (charger_id, type, created, timestamp)" in executed_sql
    assert (
        "ON monitoring_evidence "
        "(charger_id, created, timestamp, service_id, sequence_number)" in executed_sql
    )


@pytest.mark.asyncio
async def test_migrate_monitoring_evidence_trackers_adds_and_backfills_jsonb():
    service = SyncService()
    conn = AsyncMock()
    conn.scalar = AsyncMock(side_effect=[True, False])
    conn.execute = AsyncMock()

    await service._migrate_monitoring_evidence_trackers(conn)

    executed_sql = " ".join(
        str(call.args[0]) for call in conn.execute.await_args_list if call.args
    )
    assert "ADD COLUMN tracker_results JSONB NOT NULL" in executed_sql
    assert "jsonb_build_array" in executed_sql
    assert "'alarm_statistic', 'restarted_martingale'" in executed_sql


@pytest.mark.asyncio
async def test_migrate_evidence_input_timestamps_is_required_and_idempotent():
    service = SyncService()
    conn = AsyncMock()
    conn.scalar = AsyncMock(side_effect=[True, None])
    conn.execute = AsyncMock()

    await service._migrate_monitoring_evidence_input_timestamps(conn)

    executed_sql = " ".join(
        str(call.args[0]) for call in conn.execute.await_args_list if call.args
    )
    assert "ADD COLUMN input_timestamps JSONB NOT NULL" in executed_sql
    assert "UPDATE monitoring_evidence" not in executed_sql

    current_conn = AsyncMock()
    current_conn.scalar = AsyncMock(side_effect=[True, "NO"])
    current_conn.execute = AsyncMock()
    await service._migrate_monitoring_evidence_input_timestamps(current_conn)
    current_conn.execute.assert_not_awaited()

    nullable_conn = AsyncMock()
    nullable_conn.scalar = AsyncMock(side_effect=[True, "YES"])
    nullable_conn.execute = AsyncMock()
    await service._migrate_monitoring_evidence_input_timestamps(nullable_conn)
    nullable_sql = " ".join(
        str(call.args[0]) for call in nullable_conn.execute.await_args_list if call.args
    )
    assert "ALTER COLUMN input_timestamps SET NOT NULL" in nullable_sql


@pytest.mark.asyncio
async def test_migrate_monitoring_evidence_strategy_is_idempotent_and_constrained():
    service = SyncService()
    conn = AsyncMock()
    conn.scalar = AsyncMock(
        side_effect=[
            True,
            False,
            False,
            False,
            True,
            None,
            True,
            False,
            False,
        ]
    )
    conn.execute = AsyncMock()

    await service._migrate_monitoring_evidence_strategy(conn)

    executed_sql = " ".join(
        str(call.args[0]) for call in conn.execute.await_args_list if call.args
    )
    assert "ADD COLUMN strategy TEXT" in executed_sql
    assert "SET strategy = 'static_baseline'" in executed_sql
    assert "ALTER COLUMN p_value DROP NOT NULL" in executed_sql
    assert "ck_monitoring_evidence_strategy_payload" in executed_sql
    assert "anomaly_score <> 'NaN'::double precision" in executed_sql
    assert "DROP CONSTRAINT" not in executed_sql
    assert "NOT VALID" in executed_sql
    assert "VALIDATE CONSTRAINT" in executed_sql


@pytest.mark.asyncio
async def test_migrate_monitoring_evidence_strategy_performs_no_ddl_when_current():
    service = SyncService()
    conn = AsyncMock()
    conn.scalar = AsyncMock(
        side_effect=[
            True,
            True,
            True,
            True,
            False,
            "'static_baseline'::text",
            False,
            True,
            True,
        ]
    )
    conn.execute = AsyncMock()

    await service._migrate_monitoring_evidence_strategy(conn)

    conn.execute.assert_not_awaited()


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


def test_monitoring_evidence_tracker_results_uses_postgresql_jsonb():
    ddl = str(
        CreateTable(MonitoringEvidence.__table__).compile(dialect=postgresql.dialect())
    )

    tracker_results_ddl = next(
        line for line in ddl.splitlines() if "tracker_results" in line
    )
    assert "JSONB" in tracker_results_ddl
    assert "DEFAULT '[]'" in tracker_results_ddl
    assert "NOT NULL" in tracker_results_ddl


def test_monitoring_evidence_input_timestamps_uses_required_postgresql_jsonb():
    ddl = str(
        CreateTable(MonitoringEvidence.__table__).compile(dialect=postgresql.dialect())
    )
    input_timestamps_ddl = next(
        line for line in ddl.splitlines() if "input_timestamps" in line
    )
    assert "JSONB" in input_timestamps_ddl
    assert "NOT NULL" in input_timestamps_ddl


def test_monitoring_evidence_strategy_payload_ddl_supports_both_lanes():
    ddl = str(
        CreateTable(MonitoringEvidence.__table__).compile(dialect=postgresql.dialect())
    )

    assert "strategy TEXT DEFAULT 'static_baseline' NOT NULL" in ddl
    assert "p_value FLOAT" in ddl
    assert "p_value FLOAT NOT NULL" not in ddl
    assert "anomaly_score FLOAT" in ddl
    assert "ck_monitoring_evidence_strategy_payload" in ddl
    assert "'Infinity'::double precision" in ddl
