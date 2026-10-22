"""Current-schema bootstrap and database declaration checks."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from off_key_core.db.models import MonitoringEvidence, MonitoringService
from off_key_core.db.schema import bootstrap_schema, validate_existing_schema
from off_key_db_sync.service import SyncService
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, RuntimeError("obsolete schema")])
async def test_bootstrap_controls_readiness(failure):
    connection = AsyncMock()
    connection.run_sync.side_effect = failure

    @asynccontextmanager
    async def begin():
        yield connection

    engine = MagicMock()
    engine.begin = begin
    service = SyncService()
    with patch("off_key_db_sync.service.get_async_engine", return_value=engine):
        assert await service._initialize_database() is (failure is None)
    assert service.schema_ready is (failure is None)
    connection.run_sync.assert_awaited_once_with(bootstrap_schema)


def test_unsupported_schema_is_rejected_before_any_ddl():
    connection = MagicMock()
    inspector = MagicMock()
    inspector.get_table_names.return_value = ["anomalies"]
    inspector.get_columns.return_value = [{"name": "obsolete_column"}]
    inspector.get_pk_constraint.return_value = {"constrained_columns": [], "name": None}
    inspector.get_check_constraints.return_value = []
    inspector.get_foreign_keys.return_value = []
    with (
        patch("off_key_core.db.schema.inspect", return_value=inspector),
        pytest.raises(RuntimeError, match=r"Unsupported schema.*anomalies"),
    ):
        bootstrap_schema(connection)
    connection.execute.assert_not_called()


def test_empty_schema_is_supported():
    inspector = MagicMock()
    inspector.get_table_names.return_value = []
    with patch("off_key_core.db.schema.inspect", return_value=inspector):
        validate_existing_schema(MagicMock())


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


@pytest.mark.asyncio
async def test_database_wait_retries_until_the_connection_answers(monkeypatch):
    service = SyncService()
    answers = AsyncMock(side_effect=[False, False, True])
    sleep = AsyncMock()
    monkeypatch.setattr(service, "_check_database_connection", answers)
    monkeypatch.setattr("off_key_db_sync.service.asyncio.sleep", sleep)

    assert await service._wait_for_database(max_retries=3, delay=2) is True
    assert answers.await_count == 3
    assert sleep.await_args_list == [((2,),), ((2,),)]

    answers = AsyncMock(return_value=False)
    monkeypatch.setattr(service, "_check_database_connection", answers)
    assert await service._wait_for_database(max_retries=2, delay=0) is False
    assert answers.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("available", "initialised", "error"),
    [
        (False, True, "Database not available"),
        (True, False, "Database initialization failed"),
    ],
)
async def test_failed_start_raises_and_reports_stopped(
    monkeypatch, available, initialised, error
):
    service = SyncService()
    monkeypatch.setattr(
        service, "_wait_for_database", AsyncMock(return_value=available)
    )
    monkeypatch.setattr(
        service, "_initialize_database", AsyncMock(return_value=initialised)
    )

    with pytest.raises(RuntimeError, match=error):
        await service.start()
    assert service.get_health_status() == {
        "status": "stopped",
        "schema_ready": False,
        "initial_sync_complete": False,
    }


@pytest.mark.asyncio
async def test_run_serves_until_shutdown_then_stops(monkeypatch):
    service = SyncService()
    observed = []

    def shutdown():
        observed.append(service.get_health_status()["status"])
        service.shutdown_event.set()

    async def ready():
        service.schema_ready = True
        # Runs once start() has returned and run() waits for the signal.
        asyncio.get_running_loop().call_soon(shutdown)
        return True

    monkeypatch.setattr(service, "_wait_for_database", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "_initialize_database", ready)
    monkeypatch.setattr("off_key_db_sync.service.signal.signal", MagicMock())

    await service.run()

    assert observed == ["healthy"]
    assert service.get_health_status()["status"] == "stopped"
