"""Dojo label suggestions: alarms live monitors recorded on a dataset's readings."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from off_key_core.db.models import (
    Anomaly,
    DeploymentMaintenance,
    DojoDataset,
    DojoLabel,
    DojoPoint,
    DojoSeries,
    SystemCollectionConfiguration,
    Telemetry,
    User,
)
from off_key_core.schemas.alarms import MULTIVARIATE_TELEMETRY_TYPE
from off_key_core.schemas.dojo import (
    CsvImportQuery,
    DatasetFromHistory,
    LabelCreate,
    LabelSuggestionQuery,
)
from off_key_core.schemas.system import SystemDocument
from off_key_core.schemas.system_collection import (
    SystemCollectionDefinition,
    build_bindings,
)
from off_key_tactic_middleware.domain import ConflictError, NotFoundError
from off_key_tactic_middleware.services.dojo import labels as labels_module
from off_key_tactic_middleware.services.dojo.datasets import DojoDatasets
from off_key_tactic_middleware.services.dojo.labels import DojoLabels
from sqlalchemy import MetaData

from tests.support.env import set_auth_env
from tests.support.gateway import gateway_app
from tests.support.http import asgi_client
from tests.support.membership import bootstrap
from tests.support.tokens import access_token

T0 = datetime(2026, 3, 1, tzinfo=UTC)


def at(minute: float) -> datetime:
    return T0 + timedelta(minutes=minute)


def catalogue() -> SystemDocument:
    """One room with two readings; only temperature is copied into the dataset."""
    return SystemDocument.model_validate(
        {
            "label": "Workshop",
            "connections": [{"id": "broker-1", "label": "MQTT", "host": "localhost"}],
            "devices": [
                {"id": "room-1", "label": "Office", "kind": "room"},
                {"id": "room-2", "label": "Lab", "kind": "room"},
            ],
            "streams": [
                {
                    "id": f"{name}-{room}",
                    "label": name.title(),
                    "connection_id": "broker-1",
                    "device_id": f"room-{room}",
                    "topic": f"home/room-{room}/environment",
                    "payload_pointer": f"/readings/{name}",
                }
                for room in (1, 2)
                for name in ("temperature", "humidity")
            ],
        }
    )


@pytest_asyncio.fixture
async def sessions(member_database, monkeypatch):
    set_auth_env(monkeypatch)
    engine, factory = member_database
    async with engine.begin() as connection:
        # Copies skip the hypertable hooks, whose function lives outside the
        # test's schema.
        for table in (Telemetry, Anomaly):
            await connection.run_sync(table.__table__.to_metadata(MetaData()).create)
        for table in (
            DeploymentMaintenance,
            SystemCollectionConfiguration,
            DojoDataset,
            DojoSeries,
            DojoPoint,
            DojoLabel,
        ):
            await connection.run_sync(table.__table__.create)
    document = catalogue()
    bindings = build_bindings(document)
    async with factory() as session:
        session.add(
            SystemCollectionConfiguration(
                id=1,
                revision=1,
                document=SystemCollectionDefinition(
                    document=document, bindings=bindings
                ).model_dump(mode="json"),
                updated_by="test",
            )
        )
        temperature = bindings["temperature-1"]
        session.add_all(
            Telemetry(
                charger_id=temperature.entity_id,
                type=temperature.telemetry_key,
                timestamp=at(minute),
                value=float(minute),
                data_source="test",
            )
            for minute in range(60)
        )
        await session.commit()
    return factory, bindings


def alarm(binding, minute, *, monitor="", key=None, sensors=None):
    return Anomaly(
        charger_id=binding.entity_id,
        timestamp=at(minute),
        telemetry_type=key or binding.telemetry_key,
        service_id=monitor,
        anomaly_type="score",
        anomaly_value=0.9,
        sensor_set=sensors,
    )


async def copied(factory):
    async with factory() as session:
        return await DojoDatasets(session).import_history(
            DatasetFromHistory(
                name="Office", reading_ids=["temperature-1"], start=T0, end=at(60)
            ),
            created_by=None,
        )


@pytest.mark.asyncio
async def test_recorded_alarms_on_the_copied_readings_become_episodes(sessions):
    factory, bindings = sessions
    temperature, humidity = bindings["temperature-1"], bindings["humidity-1"]
    both = [temperature.telemetry_key, humidity.telemetry_key]
    view = await copied(factory)
    async with factory() as session:
        session.add_all(
            [
                # Before the dataset's first value.
                alarm(temperature, -10, monitor="m1"),
                # One episode of two monitors, eight minutes apart.
                alarm(temperature, 5, monitor="m1"),
                alarm(temperature, 13, monitor="m2"),
                # A multivariate alarm that used the copied reading.
                alarm(
                    temperature,
                    30,
                    monitor="m3",
                    key=MULTIVARIATE_TELEMETRY_TYPE,
                    sensors=both,
                ),
                # Other readings, and a multivariate alarm that cannot say
                # which readings it used while humidity was left out.
                alarm(humidity, 40, monitor="m1"),
                alarm(bindings["temperature-2"], 41, monitor="m1"),
                alarm(temperature, 45, key=MULTIVARIATE_TELEMETRY_TYPE),
                # A manual alarm on the dataset's last value.
                alarm(temperature, 59),
            ]
        )
        await session.commit()
    async with factory() as session:
        found = await DojoLabels(session).suggestions(view.id, LabelSuggestionQuery())
        split = await DojoLabels(session).suggestions(
            view.id, LabelSuggestionQuery(gap_seconds=60)
        )
    assert not found.truncated
    assert [
        (item.start_at, item.end_at, item.alarm_count, item.monitor_ids)
        for item in found.items
    ] == [
        (at(5), at(13), 2, ["m1", "m2"]),
        (at(30), at(30) + timedelta(seconds=1), 1, ["m3"]),
        (at(59), at(59) + timedelta(seconds=1), 1, []),
    ]
    assert {tuple(item.reading_ids) for item in found.items} == {("temperature-1",)}
    assert [item.start_at for item in split.items] == [at(5), at(13), at(30), at(59)]


@pytest.mark.asyncio
async def test_suggestions_are_bounded_and_skip_uploads(sessions, monkeypatch):
    factory, bindings = sessions
    view = await copied(factory)
    async with factory() as session:
        session.add_all(
            alarm(bindings["temperature-1"], minute, monitor="m1")
            for minute in range(0, 60, 20)
        )
        await session.commit()
        upload = await DojoDatasets(session).import_csv(
            f"time,u\n{T0.isoformat()},1\n{at(59).isoformat()},2\n".encode(),
            CsvImportQuery(name="Upload"),
            created_by=None,
        )
    monkeypatch.setattr(labels_module, "MAX_LABEL_SUGGESTIONS", 2)
    async with factory() as session:
        service = DojoLabels(session)
        few = await service.suggestions(view.id, LabelSuggestionQuery(gap_seconds=0))
        assert (
            await service.suggestions(upload.id, LabelSuggestionQuery())
        ).items == []
        with pytest.raises(NotFoundError):
            await service.suggestions("missing", LabelSuggestionQuery())
    assert few.truncated
    assert [item.start_at for item in few.items] == [at(0), at(20)]
    monkeypatch.setattr(labels_module, "MAX_SUGGESTION_ALARMS", 1)
    async with factory() as session:
        one = await DojoLabels(session).suggestions(view.id, LabelSuggestionQuery())
    assert one.truncated
    assert [item.alarm_count for item in one.items] == [1]


@pytest.mark.asyncio
async def test_route_suggests_labels_to_members_who_may_use_the_dojo(sessions):
    factory, bindings = sessions
    view = await copied(factory)
    async with factory() as session:
        session.add(alarm(bindings["temperature-1"], 5, monitor="m1"))
        await session.commit()
    creator = await bootstrap(factory)
    async with factory() as session:
        admin = await session.get(User, creator)
    application = gateway_app(sessions=factory)
    path = f"/v1/dojo/datasets/{view.id}/label-suggestions"
    async with asgi_client(application) as client:
        listed = await client.get(
            path,
            params={"gap_seconds": 30},
            headers={"Authorization": f"Bearer {access_token(admin)}"},
        )
        anonymous = await client.get(path)
    assert listed.status_code == 200, listed.text
    assert [item["alarm_count"] for item in listed.json()["items"]] == [1]
    assert anonymous.status_code == 401


@pytest.mark.asyncio
async def test_a_batch_adds_every_label_or_none(sessions, monkeypatch):
    factory, _ = sessions
    view = await copied(factory)

    def label(start, end):
        return LabelCreate(start_at=at(start), end_at=at(end), note="Recorded alarm")

    async with factory() as session:
        service = DojoLabels(session)
        added = await service.create_many(
            view.id, [label(1, 2), label(2, 3), label(10, 12)], created_by=None
        )
        assert [item.start_at for item in added] == [at(1), at(2), at(10)]
        # One label overlapping another of the same batch refuses all of them.
        with pytest.raises(ConflictError, match="may not overlap"):
            await service.create_many(
                view.id, [label(20, 22), label(21, 23)], created_by=None
            )
        await session.rollback()
        monkeypatch.setattr(labels_module, "MAX_DATASET_LABELS", 4)
        with pytest.raises(ConflictError, match="at most 4"):
            await service.create_many(
                view.id, [label(30, 31), label(40, 41)], created_by=None
            )
        await session.rollback()
        stored = await service.list(view.id)
    assert [item.start_at for item in stored.items] == [at(1), at(2), at(10)]
