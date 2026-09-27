"""Run against an explicitly supplied disposable TimescaleDB database."""

import os
from datetime import UTC, datetime, timedelta

import pytest
from off_key_core.config.telemetry import get_telemetry_settings
from off_key_core.db.models import (
    Anomaly,
    AnomalyIdentity,
    MonitoringEvidence,
    Telemetry,
)
from off_key_core.db.retention import read_storage_status
from off_key_core.db.schema import bootstrap_schema
from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


@pytest.mark.asyncio
async def test_current_schema_bootstrap_and_integrity():
    url = os.getenv("TEST_SCHEMA_DATABASE_URL")
    if not url:
        pytest.skip("TEST_SCHEMA_DATABASE_URL requires a disposable TimescaleDB")
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(bootstrap_schema)
            await connection.run_sync(bootstrap_schema)
            hypertables = await connection.scalars(
                text("SELECT hypertable_name FROM timescaledb_information.hypertables")
            )
            assert {"telemetry", "anomalies", "monitoring_evidence"} <= set(hypertables)
            timestamp = datetime.now(UTC)
            await connection.execute(
                insert(Anomaly).values(
                    charger_id="schema-test",
                    timestamp=timestamp,
                    telemetry_type="cpu",
                    anomaly_type="ml_adaptive_stream_univariate",
                    anomaly_value=0.9,
                    value_type="anomaly_score",
                    sensor_set=["cpu"],
                )
            )
            identity_query = (
                select(func.count())
                .select_from(AnomalyIdentity)
                .where(AnomalyIdentity.charger_id == "schema-test")
            )
            assert await connection.scalar(identity_query) == 1
            for sequence, strategy in enumerate(
                ("static_baseline", "adaptive_stream"), start=1
            ):
                await connection.execute(
                    insert(MonitoringEvidence).values(
                        service_id="schema-test",
                        timestamp=timestamp,
                        sequence_number=sequence,
                        charger_id="schema-test",
                        sensor_set=["cpu"],
                        input_timestamps={"cpu": timestamp.isoformat()},
                        strategy=strategy,
                        p_value=0.01 if strategy == "static_baseline" else None,
                        anomaly_score=0.9 if strategy == "adaptive_stream" else None,
                        threshold=0.5,
                    )
                )
            await connection.run_sync(bootstrap_schema)
            assert await connection.scalar(identity_query) == 1
            savepoint = await connection.begin_nested()
            with pytest.raises(IntegrityError):
                await connection.execute(
                    text(
                        "UPDATE monitoring_evidence SET anomaly_score = 'NaN' "
                        "WHERE service_id = 'schema-test' "
                        "AND strategy = 'adaptive_stream'"
                    )
                )
            await savepoint.rollback()
            await connection.execute(
                delete(Anomaly).where(Anomaly.charger_id == "schema-test")
            )
            assert await connection.scalar(identity_query) == 0
            savepoint = await connection.begin_nested()
            await connection.execute(
                text("ALTER TABLE monitoring_evidence ADD COLUMN obsolete TEXT")
            )
            with pytest.raises(RuntimeError, match="Unsupported schema"):
                await connection.run_sync(bootstrap_schema)
            await savepoint.rollback()
            await connection.run_sync(bootstrap_schema)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_retention_changes_existing_jobs_and_reports_persisted_state(monkeypatch):
    url = os.getenv("TEST_SCHEMA_DATABASE_URL")
    if not url:
        pytest.skip("TEST_SCHEMA_DATABASE_URL requires a disposable TimescaleDB")
    engine = create_async_engine(url)

    async def bootstrap(days):
        monkeypatch.setenv("TELEMETRY_RETENTION_DAYS", str(days))
        get_telemetry_settings.cache_clear()
        async with engine.begin() as connection:
            await connection.run_sync(bootstrap_schema)

    async def jobs():
        async with engine.connect() as connection:
            rows = await connection.execute(
                text(
                    "SELECT hypertable_name, job_id, schedule_interval, "
                    "config, scheduled "
                    "FROM timescaledb_information.jobs "
                    "WHERE hypertable_schema = 'public' "
                    "AND proc_name = 'policy_retention'"
                )
            )
            return {row["hypertable_name"]: row for row in rows.mappings()}

    async def run_telemetry_retention(job_id):
        async with engine.connect() as connection:
            await connection.execution_options(isolation_level="AUTOCOMMIT")
            await connection.execute(text("CALL run_job(:id)"), {"id": job_id})
            return list(
                await connection.scalars(
                    select(Telemetry.value)
                    .where(Telemetry.charger_id == "retention-test")
                    .order_by(Telemetry.timestamp)
                )
            )

    try:
        await bootstrap(14)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "CREATE TABLE retention_unmanaged (timestamp timestamptz NOT NULL)"
                )
            )
            await connection.execute(
                text("SELECT create_hypertable('retention_unmanaged', 'timestamp')")
            )
            await connection.execute(
                text(
                    "SELECT add_retention_policy("
                    "'retention_unmanaged', INTERVAL '35 days')"
                )
            )
            await connection.execute(
                text(
                    "SELECT alter_job(job_id, schedule_interval => INTERVAL '6 hours') "
                    "FROM timescaledb_information.jobs "
                    "WHERE hypertable_name = 'telemetry' "
                    "AND proc_name = 'policy_retention'"
                )
            )
        before = await jobs()
        for days in (30, 7, 7):
            await bootstrap(days)
            current = await jobs()
            for table in ("telemetry", "monitoring_evidence"):
                assert current[table]["job_id"] == before[table]["job_id"]
                assert (
                    current[table]["schedule_interval"]
                    == before[table]["schedule_interval"]
                )
                assert current[table]["config"]["drop_after"] == f"{days} days"
                assert current[table]["scheduled"]
            assert current["retention_unmanaged"] == before["retention_unmanaged"]

        async with engine.begin() as connection:
            await connection.execute(
                text("SELECT alter_job(:id, scheduled => false)"),
                {"id": before["telemetry"]["job_id"]},
            )
            await connection.execute(
                text("SELECT remove_retention_policy('monitoring_evidence')")
            )
        # A different process setting must not masquerade as the applied policy.
        monkeypatch.setenv("TELEMETRY_RETENTION_DAYS", "90")
        get_telemetry_settings.cache_clear()
        async with AsyncSession(engine) as session:
            status = await read_storage_status(session)
        assert status.database_size_bytes > 0
        assert status.checked_at.tzinfo is not None
        assert [policy.model_dump() for policy in status.retention_policies] == [
            {"table": "telemetry", "retention_days": 7.0, "scheduled": False},
            {
                "table": "monitoring_evidence",
                "retention_days": None,
                "scheduled": False,
            },
        ]

        await bootstrap(90)
        async with AsyncSession(engine) as session:
            status = await read_storage_status(session)
        assert all(
            policy.retention_days == 90 and policy.scheduled
            for policy in status.retention_policies
        )
        now = datetime.now(UTC)
        async with engine.begin() as connection:
            await connection.execute(
                insert(Telemetry),
                [
                    {
                        "charger_id": "retention-test",
                        "timestamp": now - timedelta(days=60),
                        "type": "temperature",
                        "value": 10,
                        "data_source": "test",
                    },
                    {
                        "charger_id": "retention-test",
                        "timestamp": now,
                        "type": "temperature",
                        "value": 20,
                        "data_source": "test",
                    },
                ],
            )
        job_id = before["telemetry"]["job_id"]
        assert await run_telemetry_retention(job_id) == [10, 20]
        await bootstrap(7)
        assert await run_telemetry_retention(job_id) == [20]
        await bootstrap(30)
        assert await run_telemetry_retention(job_id) == [20]
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE IF EXISTS retention_unmanaged"))
            await connection.execute(
                delete(Telemetry).where(Telemetry.charger_id == "retention-test")
            )
        get_telemetry_settings.cache_clear()
        await engine.dispose()
