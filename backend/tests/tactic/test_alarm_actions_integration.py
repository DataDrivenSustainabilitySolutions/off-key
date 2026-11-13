"""Real database checks for event links and reviewed bulk deletion."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from off_key_core.db.migrate import apply_migrations
from off_key_core.db.models import (
    AlarmDeletion,
    Anomaly,
    AnomalyIdentity,
    MonitoringEvidence,
)
from off_key_core.schemas.alarms import AlarmQuery, AlarmSelection
from off_key_core.schemas.system import SystemDocument, SystemRuntime, SystemSnapshot
from off_key_tactic_middleware.domain import NotFoundError, ValidationError
from off_key_tactic_middleware.services.data.alarm_actions import AlarmActions
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

CATALOGUE = SystemSnapshot(
    revision=1,
    storage_origin="saved",
    document=SystemDocument(
        connections=[{"id": "broker", "label": "Plant MQTT", "host": "broker"}],
        devices=[{"id": "line", "label": "Line 1", "connection_id": "broker"}],
        streams=[
            {
                "id": key,
                "label": key.title(),
                "connection_id": "broker",
                "device_id": "line",
                "topic": f"line/{key}",
            }
            for key in ("temperature", "pressure")
        ],
    ),
    runtime=SystemRuntime(
        bindings={
            key: {"entity_id": "busy", "telemetry_key": key}
            for key in ("temperature", "pressure")
        }
    ),
)


def anomaly(time, key="temperature", **overrides):
    return Anomaly(
        **{
            "charger_id": "busy",
            "timestamp": time,
            "telemetry_type": key,
            "service_id": "monitor-a",
            "anomaly_type": "ml_conformal_static_univariate",
            "anomaly_value": 0.0001,
            "value_type": "conformal_pvalue",
            "sensor_set": None,
            **overrides,
        }
    )


@pytest_asyncio.fixture
async def actions_db(disposable_database):
    with disposable_database.begin() as connection:
        apply_migrations(connection)
    engine = create_async_engine(
        disposable_database.url.set(drivername="postgresql+asyncpg")
    )
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    at = datetime.now(UTC) - timedelta(hours=1)
    async with sessions.begin() as session:
        session.add_all([anomaly(at - timedelta(seconds=n)) for n in range(501)])
        session.add_all(
            [
                anomaly(at, "pressure", anomaly_value=0.02),
                anomaly(
                    at,
                    "__multivariate__",
                    sensor_set=["temperature", "pressure"],
                    anomaly_type="ml_conformal_static_multivariate",
                ),
                anomaly(
                    at,
                    service_id="adaptive",
                    anomaly_value=0.00001,
                    value_type="anomaly_score",
                    anomaly_type="ml_adaptive_stream_univariate",
                ),
                anomaly(at, charger_id="quiet"),
                anomaly(at, charger_id="removed"),
            ]
        )
    try:
        yield sessions, at
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_bulk_delete_freezes_all_pages_and_retries_without_widening(actions_db):
    sessions, at = actions_db
    async with sessions() as session:
        actions = AlarmActions(session)
        excluded = await session.scalar(
            select(AnomalyIdentity.anomaly_id).where(
                AnomalyIdentity.charger_id == "busy",
                AnomalyIdentity.timestamp == at,
                AnomalyIdentity.telemetry_type == "temperature",
                AnomalyIdentity.service_id == "monitor-a",
            )
        )
        preview = await actions.preview(
            AlarmSelection(
                query=AlarmQuery(
                    reading_ids=["temperature"],
                    max_p_value=0.001,
                    since=at - timedelta(hours=1),
                    until=at + timedelta(hours=1),
                    limit=1,
                ),
                exclude_ids=[excluded],
            ),
            CATALOGUE,
        )
        assert (
            preview.count == 501
        )  # 500 univariate + the joint event, beyond page one.
        frozen = await session.get(AlarmDeletion, preview.token)
        assert len(frozen.alarm_ids) == 501
        assert excluded not in frozen.alarm_ids

        # A concurrent deletion changes the actual count. A late/backdated
        # arrival satisfies the original filters but was not reviewed.
        await session.execute(
            delete(Anomaly).where(
                Anomaly.charger_id == "busy",
                Anomaly.timestamp == at - timedelta(seconds=1),
            )
        )
        session.add(anomaly(at + timedelta(minutes=1)))
        await session.commit()
        assert await actions.delete(preview.token) == 500
        assert await actions.delete(preview.token) == 500
        assert await session.scalar(select(func.count()).select_from(Anomaly)) == 6
        assert (
            await session.scalar(select(func.count()).select_from(AnomalyIdentity)) == 6
        )
        assert (await actions.detail(excluded, CATALOGUE)).alarm.alarm_id == excluded
        # Explicit IDs deduplicate, and missing IDs do not widen the selection.
        explicit = await actions.preview(
            AlarmSelection(alarm_ids=[excluded, excluded, "gone"]), CATALOGUE
        )
        assert explicit.count == 1
        assert await actions.delete(explicit.token) == 1
        with pytest.raises(NotFoundError):
            await actions.detail(excluded, CATALOGUE)


@pytest.mark.asyncio
async def test_deletion_preserves_empty_scopes_filters_and_expiry(actions_db):
    sessions, at = actions_db
    async with sessions() as session:
        actions = AlarmActions(session)
        for query, count in [
            (AlarmQuery(reading_ids=[]), 0),
            (AlarmQuery(reading_ids=["temperature"], monitor_id="adaptive"), 1),
            (AlarmQuery(reading_ids=["temperature"], reading_id="pressure"), 1),
            (AlarmQuery(reading_ids=["temperature"], until=at), 500),
            (
                AlarmQuery(
                    reading_ids=["temperature"], since=at + timedelta(seconds=1)
                ),
                0,
            ),
        ]:
            assert (
                await actions.preview(AlarmSelection(query=query), CATALOGUE)
            ).count == count
        for query in [
            AlarmQuery(reading_ids=["temperature", "gone"]),
            AlarmQuery(reading_id="gone"),
        ]:
            with pytest.raises(ValidationError, match="no longer exist"):
                await actions.preview(AlarmSelection(query=query), CATALOGUE)
        preview = await actions.preview(AlarmSelection(query=AlarmQuery()), CATALOGUE)
        assert preview.count == 506
        await session.execute(
            update(AlarmDeletion)
            .where(AlarmDeletion.id == preview.token)
            .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        await session.commit()
        with pytest.raises(NotFoundError, match="expired"):
            await actions.delete(preview.token)
        assert await session.scalar(select(func.count()).select_from(Anomaly)) == 506


@pytest.mark.asyncio
async def test_event_detail_uses_exact_monitor_time_and_device_evidence(actions_db):
    sessions, at = actions_db
    async with sessions() as session:
        event_id = await session.scalar(
            select(AnomalyIdentity.anomaly_id).where(
                AnomalyIdentity.charger_id == "busy",
                AnomalyIdentity.timestamp == at,
                AnomalyIdentity.telemetry_type == "__multivariate__",
            )
        )
        for sequence, time, monitor, device, alarm in [
            (1, at, "monitor-a", "busy", True),
            (2, at + timedelta(seconds=1), "monitor-a", "busy", True),
            (3, at, "other-monitor", "busy", True),
            (4, at, "monitor-a", "quiet", True),
            (5, at, "monitor-a", "busy", False),
        ]:
            session.add(
                MonitoringEvidence(
                    service_id=monitor,
                    timestamp=time,
                    sequence_number=sequence,
                    charger_id=device,
                    sensor_set=["temperature", "pressure"],
                    input_timestamps={
                        "temperature": at.isoformat(),
                        "pressure": (at - timedelta(seconds=2)).isoformat(),
                    },
                    strategy="static_baseline",
                    p_value=0.0001,
                    threshold=100,
                    alarm=alarm,
                )
            )
        await session.commit()
        actions = AlarmActions(session)
        detail = await actions.detail(event_id, CATALOGUE)
        assert detail.alarm.reading_ids == ["temperature", "pressure"]
        assert detail.alarm.device_id == "line"
        assert detail.evidence.sequence_number == 1
        assert detail.evidence.input_timestamps["pressure"] == at - timedelta(seconds=2)
        await session.execute(delete(MonitoringEvidence))
        await session.commit()
        assert (await actions.detail(event_id, CATALOGUE)).evidence is None
