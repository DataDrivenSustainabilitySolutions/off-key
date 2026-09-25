"""Run against an explicitly supplied disposable TimescaleDB database."""

import os
from datetime import UTC, datetime

import pytest
from off_key_core.db.models import Anomaly, AnomalyIdentity, MonitoringEvidence
from off_key_core.db.schema import bootstrap_schema
from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine


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
