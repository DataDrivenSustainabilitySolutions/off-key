"""Dojo datasets: CSV parsing, frozen copies of history, and admin-only routes."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from off_key_core.db.base import get_db_async
from off_key_core.db.models import (
    DeploymentMaintenance,
    DojoDataset,
    DojoPoint,
    DojoRun,
    DojoRunResult,
    DojoSeries,
    SystemCollectionConfiguration,
    Telemetry,
    User,
)
from off_key_core.schemas.dojo import (
    CsvImportQuery,
    DatasetChange,
    DatasetFromHistory,
    DatasetListQuery,
    DatasetPointsQuery,
)
from off_key_core.schemas.members import MemberInvitation
from off_key_core.schemas.system_collection import (
    SystemCollectionDefinition,
    build_bindings,
)
from off_key_tactic_middleware.api.v1.dojo import router
from off_key_tactic_middleware.domain import NotFoundError, ValidationError
from off_key_tactic_middleware.services.accounts.members import MemberService
from off_key_tactic_middleware.services.dojo import datasets as dataset_module
from off_key_tactic_middleware.services.dojo.csv_import import (
    detect_delimiter,
    parse_timestamp,
    read_points,
)
from off_key_tactic_middleware.services.dojo.datasets import DojoDatasets
from sqlalchemy import MetaData, func, select

from tests.support.env import set_auth_env
from tests.support.http import asgi_client
from tests.support.membership import PASSWORD, bootstrap
from tests.support.system_document import document
from tests.support.tokens import access_token

T0 = datetime(2026, 3, 1, tzinfo=UTC)


def points(body: str, **query):
    declared, rows = read_points(body.encode(), CsvImportQuery(name="test", **query))
    return declared, list(rows)


def test_history_series_names_preserve_labels_that_already_contain_suffixes():
    labels = ["Temperature", "Temperature", "Temperature (2)", "Temperature"]
    assert dataset_module._unique_names(labels) == [
        "Temperature",
        "Temperature (3)",
        "Temperature (2)",
        "Temperature (4)",
    ]


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------


def test_wide_csv_reads_one_series_per_column_and_skips_empty_cells():
    declared, rows = points(
        "time,temperature,humidity\n"
        "2026-03-01T00:00:00Z,20.5,40\n"
        "2026-03-01T00:01:00Z,,41\n"
    )
    assert declared == ["temperature", "humidity"]
    assert rows == [
        ("temperature", T0, 20.5),
        ("humidity", T0, 40.0),
        ("humidity", T0 + timedelta(minutes=1), 41.0),
    ]


def test_long_csv_names_series_where_they_appear():
    declared, rows = points(
        "Series,Timestamp,Value\nflow,2026-03-01 00:00:00,1.5\npressure,1772323200,2\n",
        layout="long",
    )
    assert declared == []
    assert rows == [("flow", T0, 1.5), ("pressure", T0, 2.0)]


def test_semicolon_csv_accepts_a_decimal_comma():
    declared, rows = points("zeit;wert\n2026-03-01T01:00:00+01:00;1,25\n")
    assert declared == ["wert"]
    assert rows == [("wert", T0, 1.25)]


def test_named_timestamp_column_may_sit_anywhere():
    declared, rows = points("a,at,b\n1,2026-03-01T00:00:00Z,2\n", timestamp_column="AT")
    assert declared == ["a", "b"]
    assert rows == [("a", T0, 1.0), ("b", T0, 2.0)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-03-01T00:00:00", T0),
        ("2026-03-01T00:00:00Z", T0),
        ("1772323200", T0),
        ("1772323200000", T0),
        ("1772323200.5", T0 + timedelta(milliseconds=500)),
    ],
)
def test_timestamps_are_iso_or_epoch_and_default_to_utc(text, expected):
    assert parse_timestamp(text) == expected


def test_delimiter_follows_the_header():
    assert detect_delimiter("a;b;c") == ";"
    assert detect_delimiter("a\tb") == "\t"
    assert detect_delimiter("single") == ","


@pytest.mark.parametrize(
    ("body", "query", "message"),
    [
        ("", {}, "empty"),
        ("time\n2026-03-01,1\n", {}, "at least one value column"),
        ("time,a,a\n", {}, "unique"),
        ("time,a\nyesterday,1\n", {}, "Line 2"),
        ("time,a\n2026-03-01,warm\n", {}, "'warm' in 'a'"),
        ("time,a\n2026-03-01,nan\n", {}, "finite"),
        ("series,timestamp\n", {"layout": "long"}, "column named 'value'"),
    ],
)
def test_unreadable_csv_names_the_problem(body, query, message):
    with pytest.raises(ValidationError, match=message):
        points(body, **query)


def test_non_utf8_csv_is_rejected():
    with pytest.raises(ValidationError, match="UTF-8"):
        _, rows = read_points(b"time,a\n2026-03-01,\xff\n", CsvImportQuery(name="x"))
        list(rows)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def dojo_database(member_database, monkeypatch):
    set_auth_env(monkeypatch)
    engine, sessions = member_database
    async with engine.begin() as connection:
        # A copy of the telemetry table skips its hypertable hook, whose
        # function lives outside this test's schema.
        await connection.run_sync(Telemetry.__table__.to_metadata(MetaData()).create)
        for table in (
            DeploymentMaintenance,
            SystemCollectionConfiguration,
            DojoDataset,
            DojoSeries,
            DojoPoint,
            DojoRun,
            DojoRunResult,
        ):
            await connection.run_sync(table.__table__.create)
    return sessions


async def admin_id(sessions):
    return await bootstrap(sessions)


@pytest.mark.asyncio
async def test_csv_import_stores_series_and_pages_points(dojo_database, monkeypatch):
    monkeypatch.setattr(dataset_module, "COPY_BATCH", 2)
    creator = await admin_id(dojo_database)
    rows = "\n".join(
        f"{(T0 + timedelta(minutes=i)).isoformat()},{i},{'' if i % 2 else i * 10}"
        for i in range(5)
    )
    async with dojo_database() as session:
        view = await DojoDatasets(session).import_csv(
            f"time,a,b,never\n{rows}\n".encode(),
            CsvImportQuery(name="  Pump trip  ", filename="pump.csv"),
            created_by=creator,
        )
    assert view.name == "Pump trip"
    assert view.origin == "csv"
    assert view.point_count == 8
    assert (view.start_at, view.end_at) == (T0, T0 + timedelta(minutes=4))
    assert [(item.name, item.position, item.point_count) for item in view.series] == [
        ("a", 0, 5),
        ("b", 1, 3),
    ]
    assert view.source["filename"] == "pump.csv"
    async with dojo_database() as session:
        service = DojoDatasets(session)
        first = await service.points(
            view.id, view.series[0].id, DatasetPointsQuery(limit=3)
        )
        rest = await service.points(
            view.id,
            view.series[0].id,
            DatasetPointsQuery(after=first.next_after, limit=3),
        )
        listed = await service.list(DatasetListQuery())
    assert [item.value for item in first.items] == [0, 1, 2]
    assert [item.value for item in rest.items] == [3, 4]
    assert rest.next_after is None
    assert [(item.id, item.series_count) for item in listed.items] == [(view.id, 2)]


@pytest.mark.asyncio
async def test_rejected_csv_leaves_nothing_behind(dojo_database, monkeypatch):
    monkeypatch.setattr(dataset_module, "COPY_BATCH", 1)
    async with dojo_database() as session:
        with pytest.raises(ValidationError, match="same timestamp"):
            await DojoDatasets(session).import_csv(
                b"time,a\n2026-03-01T00:00:00Z,1\n2026-03-01T00:00:00Z,2\n",
                CsvImportQuery(name="duplicate"),
                created_by=None,
            )
        await session.rollback()
    monkeypatch.setattr(dataset_module, "MAX_DATASET_POINTS", 2)
    async with dojo_database() as session:
        with pytest.raises(ValidationError, match="at most 2 points"):
            await DojoDatasets(session).import_csv(
                b"time,a\n1,1\n2,2\n3,3\n", CsvImportQuery(name="big"), created_by=None
            )
        await session.rollback()
    async with dojo_database() as session:
        assert await session.scalar(select(func.count()).select_from(DojoDataset)) == 0
        assert await session.scalar(select(func.count()).select_from(DojoPoint)) == 0


async def seed_history(sessions):
    catalogue = document()
    bindings = build_bindings(catalogue)
    definition = SystemCollectionDefinition(document=catalogue, bindings=bindings)
    binding = bindings["temperature-1"]
    async with sessions() as session:
        session.add(
            SystemCollectionConfiguration(
                id=1,
                revision=1,
                document=definition.model_dump(mode="json"),
                updated_by="test",
            )
        )
        session.add_all(
            Telemetry(
                charger_id=binding.entity_id,
                type=binding.telemetry_key,
                timestamp=T0 + timedelta(minutes=i),
                value=float(i),
                data_source="test",
            )
            for i in range(10)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_history_copy_is_frozen_and_keeps_its_reading(dojo_database):
    await seed_history(dojo_database)
    request = DatasetFromHistory(
        name="Office",
        reading_ids=["temperature-1"],
        start=T0 + timedelta(minutes=2),
        end=T0 + timedelta(minutes=6),
    )
    async with dojo_database() as session:
        view = await DojoDatasets(session).import_history(request, created_by=None)
    assert view.origin == "history"
    assert view.point_count == 4
    [series] = view.series
    assert (series.name, series.unit, series.reading_id) == (
        "Temperature",
        "°C",
        "temperature-1",
    )
    assert (series.start_at, series.end_at) == (
        T0 + timedelta(minutes=2),
        T0 + timedelta(minutes=5),
    )
    async with dojo_database() as session:
        await session.execute(Telemetry.__table__.delete())
        await session.commit()
        page = await DojoDatasets(session).points(
            view.id, series.id, DatasetPointsQuery()
        )
    assert [item.value for item in page.items] == [2, 3, 4, 5]


@pytest.mark.asyncio
async def test_history_copy_rejects_unknown_readings_and_empty_windows(dojo_database):
    await seed_history(dojo_database)
    async with dojo_database() as session:
        service = DojoDatasets(session)
        with pytest.raises(ValidationError, match="missing-1"):
            await service.import_history(
                DatasetFromHistory(
                    name="x",
                    reading_ids=["missing-1"],
                    start=T0,
                    end=T0 + timedelta(hours=1),
                ),
                created_by=None,
            )

        with pytest.raises(ValidationError, match="recorded nothing"):
            await service.import_history(
                DatasetFromHistory(
                    name="x",
                    reading_ids=["temperature-1"],
                    start=T0 - timedelta(days=2),
                    end=T0 - timedelta(days=1),
                ),
                created_by=None,
            )


@pytest.mark.asyncio
async def test_history_budget_is_checked_against_actual_copied_points(
    dojo_database, monkeypatch
):
    await seed_history(dojo_database)
    monkeypatch.setattr(dataset_module, "MAX_DATASET_POINTS", 10)
    async with dojo_database() as session:
        service = DojoDatasets(session)
        store = service._store_series

        async def store_after_late_arrival(*args):
            async with dojo_database() as writer:
                existing = await writer.scalar(select(Telemetry).limit(1))
                writer.add(
                    Telemetry(
                        charger_id=existing.charger_id,
                        type=existing.type,
                        timestamp=T0 + timedelta(seconds=1),
                        value=42,
                        data_source="test",
                    )
                )
                await writer.commit()
            await store(*args)

        monkeypatch.setattr(service, "_store_series", store_after_late_arrival)
        with pytest.raises(ValidationError, match="at most 10"):
            await service.import_history(
                DatasetFromHistory(
                    name="x",
                    reading_ids=["temperature-1"],
                    start=T0,
                    end=T0 + timedelta(hours=1),
                ),
                created_by=None,
            )
        await session.rollback()
    async with dojo_database() as session:
        assert await session.scalar(select(func.count()).select_from(DojoDataset)) == 0


@pytest.mark.asyncio
async def test_change_and_delete_cascade_to_points(dojo_database):
    async with dojo_database() as session:
        view = await DojoDatasets(session).import_csv(
            b"t,a\n1,1\n", CsvImportQuery(name="old"), created_by=None
        )
    async with dojo_database() as session:
        service = DojoDatasets(session)
        changed = await service.change(
            view.id, DatasetChange(name="new", description="Known trip")
        )
        assert (changed.name, changed.description) == ("new", "Known trip")
        await service.remove(view.id)
        assert await session.scalar(select(func.count()).select_from(DojoPoint)) == 0
        with pytest.raises(NotFoundError):
            await service.get(view.id)
        with pytest.raises(NotFoundError):
            await service.points(view.id, view.series[0].id, DatasetPointsQuery())


def dojo_app(sessions):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def database():
        async with sessions() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_async] = database
    return app


@pytest.mark.asyncio
async def test_routes_upload_csv_for_administrators_only(dojo_database):
    admin = await admin_id(dojo_database)
    async with dojo_database() as session:
        admin_user = await session.get(User, admin)
        service = MemberService(session)
        invitation = await service.invite(
            MemberInvitation(email="member@example.com", role="user"), admin_user
        )
        await service.accept_invitation(invitation["token"], PASSWORD)
    async with dojo_database() as session:
        admin_user = await session.get(User, admin)
        member = await session.scalar(
            select(User).where(User.email == "member@example.com")
        )
    async with asgi_client(dojo_app(dojo_database)) as client:
        denied = await client.get(
            "/api/v1/dojo/datasets",
            headers={"Authorization": f"Bearer {access_token(member)}"},
        )
        created = await client.post(
            "/api/v1/dojo/datasets/csv",
            params={"name": "Upload", "filename": "x.csv"},
            content=b"t;a\n2026-03-01T00:00:00Z;1,5\n",
            headers={
                "Authorization": f"Bearer {access_token(admin_user)}",
                "Content-Type": "text/csv",
            },
        )
        invalid = await client.post(
            "/api/v1/dojo/datasets/csv",
            params={"name": "Upload"},
            content=b"t,a\nsoon,1\n",
            headers={"Authorization": f"Bearer {access_token(admin_user)}"},
        )
    assert denied.status_code == 403
    assert created.status_code == 201, created.text
    assert created.json()["created_by"] == admin
    assert created.json()["series"][0]["name"] == "a"
    assert invalid.status_code == 422
    assert "Line 2" in invalid.json()["detail"]
