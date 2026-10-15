"""Exercise monitor alarm identity and upgrades against real TimescaleDB."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from off_key_core.db.migrate import apply_migrations, migration_status
from off_key_core.db.models import Anomaly, AnomalyIdentity, MonitoringEvidence
from off_key_mqtt_radar.config.config import MQTTRadarConfig
from off_key_mqtt_radar.database import DatabaseWriter
from off_key_mqtt_radar.models import AnomalyResult
from off_key_tactic_middleware.repositories.data import AnomalyRepository
from off_key_tactic_middleware.services.data.anomalies import AnomalyService
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_independent_monitor_alarms_survive_retries_and_independent_deletion(
    disposable_database, monkeypatch
):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    timestamp = datetime.now(UTC)
    try:
        for service_id, sensors in (
            ("monitor-a", ["a", "b"]),
            ("monitor-b", ["c", "d"]),
        ):
            monkeypatch.setattr(
                "off_key_mqtt_radar.result_records.get_radar_checkpoint_settings",
                lambda service_id=service_id: SimpleNamespace(SERVICE_ID=service_id),
            )
            result = AnomalyResult(
                anomaly_score=0.001,
                is_anomaly=True,
                severity="high",
                timestamp=timestamp,
                model_info={"model_type": "pyod_iforest"},
                raw_data=dict.fromkeys(sensors, 42.0),
                topic=f"telemetry/entity/{sensors[-1]}",
                charger_id="entity",
                context={
                    "static_conformal": {
                        "phase": "ready",
                        "p_value": 0.001,
                        "tested_count": 1,
                        "restarted_ville_threshold": 100.0,
                        "alarm_fired": True,
                    },
                    "alignment": {
                        "aligned_vector": True,
                        "required_sensors": sensors,
                        "input_timestamps": dict.fromkeys(
                            sensors, timestamp.isoformat()
                        ),
                    },
                },
            )
            writer = DatabaseWriter(MQTTRadarConfig(), session_factory=sessions)
            for _ in range(2):
                await writer.write_result(result)
                await writer._flush_batch()
            assert writer.total_errors == 0

        async with sessions() as session:
            repository = AnomalyRepository(session)
            service = AnomalyService(session, repository)
            rows = await service.list_anomalies(
                charger_id="entity", telemetry_type=None, limit=10
            )
            assert {row["service_id"] for row in rows} == {"monitor-a", "monitor-b"}
            assert len({row["anomaly_id"] for row in rows}) == 2
            assert await session.scalar(select(func.count()).select_from(Anomaly)) == 2
            assert (
                await session.scalar(
                    select(func.count()).select_from(MonitoringEvidence)
                )
                == 2
            )
            first_id = next(
                row["anomaly_id"] for row in rows if row["service_id"] == "monitor-a"
            )
            await service.delete_anomaly(anomaly_id=first_id)
            remaining = await service.list_anomalies(
                charger_id="entity", telemetry_type=None, limit=10
            )
            assert [row["service_id"] for row in remaining] == ["monitor-b"]
            assert (
                await session.scalar(select(func.count()).select_from(AnomalyIdentity))
                == 1
            )
            assert await repository.get_by_anomaly_id(anomaly_id=first_id) is None
    finally:
        await engine.dispose()


@pytest.mark.parametrize("ledger", [True, False])
def test_monitor_identity_migration_preserves_historical_public_ids(
    disposable_database, ledger
):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
        # Recreate the exact supported pre-007 identity shape, including the old
        # insert trigger. No application writers are active during this upgrade.
        connection.exec_driver_sql("""
            ALTER TABLE anomaly_identity DROP CONSTRAINT fk_anomaly_identity_anomaly;
            ALTER TABLE anomaly_identity DROP CONSTRAINT uq_anomaly_identity_target;
            ALTER TABLE anomalies DROP CONSTRAINT pk_anomaly;
            ALTER TABLE anomaly_identity DROP COLUMN service_id;
            ALTER TABLE anomalies DROP COLUMN service_id;
            ALTER TABLE anomalies ADD CONSTRAINT pk_anomaly
                PRIMARY KEY (charger_id, timestamp, telemetry_type);
            ALTER TABLE anomaly_identity ADD CONSTRAINT uq_anomaly_identity_target
                UNIQUE (charger_id, timestamp, telemetry_type);
            ALTER TABLE anomaly_identity ADD CONSTRAINT fk_anomaly_identity_anomaly
                FOREIGN KEY (charger_id, timestamp, telemetry_type)
                REFERENCES anomalies (charger_id, timestamp, telemetry_type)
                ON DELETE CASCADE;
            CREATE OR REPLACE FUNCTION off_key_sync_anomaly_identity()
            RETURNS TRIGGER AS $$
            BEGIN
                INSERT INTO anomaly_identity (charger_id, timestamp, telemetry_type)
                VALUES (NEW.charger_id, NEW.timestamp, NEW.telemetry_type)
                ON CONFLICT (charger_id, timestamp, telemetry_type) DO NOTHING;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            INSERT INTO anomalies
                (charger_id, timestamp, telemetry_type, anomaly_type, anomaly_value)
            VALUES ('historical', '2026-10-01T00:00:00Z', '__multivariate__',
                'ml_conformal_static_multivariate', 0.001);
            UPDATE anomaly_identity SET anomaly_id = 'preserved-public-id';
        """)
        if ledger:
            connection.execute(
                text(
                    "DELETE FROM off_key_schema_migrations "
                    "WHERE version = '007_monitor_anomaly_identity.sql'"
                )
            )
        else:
            connection.execute(text("DROP TABLE off_key_schema_migrations"))

    with disposable_database.begin() as connection:
        assert (
            "007_monitor_anomaly_identity.sql"
            in migration_status(connection)["pending"]
        )
        apply_migrations(connection)
        assert connection.execute(
            text("SELECT anomaly_id, service_id FROM anomaly_identity")
        ).one() == ("preserved-public-id", "")
        assert connection.scalar(text("SELECT count(*) FROM anomalies")) == 1
        connection.exec_driver_sql("""
            INSERT INTO anomalies
                (charger_id, timestamp, telemetry_type, service_id,
                    anomaly_type, anomaly_value)
            SELECT charger_id, timestamp, telemetry_type, monitor,
                anomaly_type, anomaly_value
            FROM anomalies CROSS JOIN unnest(ARRAY['monitor-a', 'monitor-b']) monitor
            WHERE service_id = '';
        """)
        assert connection.scalar(text("SELECT count(*) FROM anomalies")) == 3
        assert connection.scalar(text("SELECT count(*) FROM anomaly_identity")) == 3
        assert apply_migrations(connection)["applied"] == []
        assert (
            connection.scalar(
                text(
                    "SELECT service_id FROM anomaly_identity "
                    "WHERE anomaly_id = 'preserved-public-id'"
                )
            )
            == ""
        )
