"""Exercise monitor alarm identity and upgrades against real TimescaleDB."""

from datetime import UTC, datetime

import pytest
from off_key_core.db.migrate import apply_migrations
from off_key_core.db.models import Anomaly, AnomalyIdentity, MonitoringEvidence
from off_key_core.schemas.system import SystemDocument, SystemSnapshot
from off_key_mqtt_radar.config.config import RadarConfig
from off_key_mqtt_radar.database import DatabaseWriter
from off_key_mqtt_radar.models import AnomalyResult
from off_key_tactic_middleware.repositories.data import AnomalyRepository
from off_key_tactic_middleware.services.data.alarms import AlarmService
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tests.support.form_pipeline import form_radar_config

pytestmark = pytest.mark.radar_integration


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
            writer = DatabaseWriter(
                form_radar_config(None, ["telemetry/charger-sim-1/sine"], RadarConfig),
                session_factory=sessions,
                service_id=service_id,
            )
            for _ in range(2):
                await writer.write_result(result)
                await writer._flush_batch()
            assert writer.total_errors == 0

        async with sessions() as session:
            repository = AnomalyRepository(session)
            service = AlarmService(session, repository)

            async def every_alarm():
                return await service.list_alarms(
                    SystemSnapshot(
                        revision=0, document=SystemDocument(), storage_origin="saved"
                    ),
                    device_id=None,
                    stream_ids=None,
                    service_id=None,
                    limit=10,
                )

            rows = await every_alarm()
            assert {row.monitor_id for row in rows} == {"monitor-a", "monitor-b"}
            assert len({row.alarm_id for row in rows}) == 2
            assert await session.scalar(select(func.count()).select_from(Anomaly)) == 2
            assert (
                await session.scalar(
                    select(func.count()).select_from(MonitoringEvidence)
                )
                == 2
            )
            first_id = next(
                row.alarm_id for row in rows if row.monitor_id == "monitor-a"
            )
            await service.delete_alarm(alarm_id=first_id)
            remaining = await every_alarm()
            assert [row.monitor_id for row in remaining] == ["monitor-b"]
            assert (
                await session.scalar(select(func.count()).select_from(AnomalyIdentity))
                == 1
            )
            assert await repository.get_by_anomaly_id(anomaly_id=first_id) is None
    finally:
        await engine.dispose()
