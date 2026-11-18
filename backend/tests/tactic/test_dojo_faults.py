"""Faults written into a copy of a Dojo dataset, each labelled as a problem."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from off_key_core.db.models import (
    DeploymentMaintenance,
    DojoDataset,
    DojoLabel,
    DojoPoint,
    DojoRun,
    DojoRunResult,
    DojoSeries,
    DojoStudy,
    DojoSuite,
    DojoSuiteDataset,
)
from off_key_core.schemas.dojo import (
    CsvImportQuery,
    DatasetListQuery,
    DatasetPointsQuery,
    DatasetWithFaults,
    Fault,
    LabelCreate,
)
from off_key_tactic_middleware.domain import ValidationError
from off_key_tactic_middleware.services.dojo.datasets import DojoDatasets
from off_key_tactic_middleware.services.dojo.labels import DojoLabels
from pydantic import ValidationError as SchemaError

from tests.support.env import set_auth_env
from tests.support.membership import bootstrap

T0 = datetime(2024, 1, 1, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


@pytest_asyncio.fixture
async def sessions(member_database, monkeypatch):
    set_auth_env(monkeypatch)
    engine, factory = member_database
    async with engine.begin() as connection:
        for table in (
            DeploymentMaintenance,
            DojoDataset,
            DojoSeries,
            DojoPoint,
            DojoLabel,
            DojoSuite,
            DojoSuiteDataset,
            DojoStudy,
            DojoRun,
            DojoRunResult,
        ):
            await connection.run_sync(table.__table__.create)
    return factory


async def source(factory):
    """Two series a minute apart for an hour: a flat 10 and an alternating 0/2."""
    creator = await bootstrap(factory)
    rows = "\n".join(f"{at(i).isoformat()},10,{2 * (i % 2)}" for i in range(60))
    async with factory() as session:
        view = await DojoDatasets(session).import_csv(
            f"time,flat,wave\n{rows}\n".encode(),
            CsvImportQuery(name="Pump"),
            created_by=creator,
        )
    return creator, view


async def values(factory, dataset_id, series_id):
    async with factory() as session:
        page = await DojoDatasets(session).points(
            dataset_id, series_id, DatasetPointsQuery(limit=1000)
        )
    return {item.timestamp: item.value for item in page.items}


def fault(kind, series, start, end, size=None):
    return Fault(
        kind=kind, series_id=series, start_at=at(start), end_at=at(end), size=size
    )


@pytest.mark.asyncio
async def test_faults_are_written_into_a_copy_and_labelled(sessions):
    creator, view = await source(sessions)
    flat, wave = (item.id for item in view.series)
    async with sessions() as session:
        await DojoLabels(session).create(
            view.id,
            LabelCreate(start_at=at(0), end_at=at(2), note="known trip"),
            created_by=creator,
        )
    async with sessions() as session:
        copy = await DojoDatasets(session).inject_faults(
            view.id,
            DatasetWithFaults(
                name="Pump with faults",
                faults=[
                    fault("step", flat, 10, 14, size=5),
                    fault("drift", flat, 20, 30, size=10),
                    fault("freeze", wave, 41, 44),
                    fault("gap", wave, 50, 52),
                ],
            ),
            created_by=creator,
        )
    assert copy.id != view.id and copy.origin == "csv"
    assert copy.source["copied_from"] == view.id
    new_flat, new_wave = (item.id for item in copy.series)
    assert [item["series_id"] for item in copy.source["faults"]] == [
        new_flat,
        new_flat,
        new_wave,
        new_wave,
    ]
    written = await values(sessions, copy.id, new_flat)
    assert [written[at(i)] for i in (9, 10, 14, 15)] == [10, 15, 15, 10]
    assert [written[at(i)] for i in (20, 25, 30, 31)] == [10, 15, 20, 10]
    waves = await values(sessions, copy.id, new_wave)
    # The last value before the freeze was 0 at minute 40.
    assert [waves[at(i)] for i in range(39, 46)] == [2, 0, 0, 0, 0, 0, 2]
    assert at(50) not in waves and at(52) not in waves and waves[at(53)] == 2
    assert copy.point_count == 60 + 57
    # The source is untouched.
    assert (await values(sessions, view.id, flat))[at(12)] == 10
    async with sessions() as session:
        labels = (await DojoLabels(session).list(copy.id)).items
    assert [(item.start_at, item.end_at, item.note) for item in labels] == [
        (at(0), at(2), "known trip"),
        (at(10), at(14), "Injected step of +5 on flat"),
        (at(20), at(30), "Injected drift to +10 on flat"),
        (at(41), at(44), "Injected freeze at 0 on wave"),
        # A gap is noticed at the first value after it.
        (at(50), at(53), "Injected gap on wave"),
    ]


@pytest.mark.asyncio
async def test_a_size_left_out_is_three_standard_deviations(sessions):
    creator, view = await source(sessions)
    flat, wave = (item.id for item in view.series)
    async with sessions() as session:
        copy = await DojoDatasets(session).inject_faults(
            view.id,
            DatasetWithFaults(name="Step", faults=[fault("step", wave, 10, 11)]),
            created_by=creator,
        )
    size = copy.source["faults"][0]["size"]
    # 0/2 alternating over 60 values: a sample standard deviation near 1.008.
    assert size == pytest.approx(3 * 1.00844, rel=1e-3)
    async with sessions() as session:
        with pytest.raises(ValidationError, match="does not vary, so give a size"):
            await DojoDatasets(session).inject_faults(
                view.id,
                DatasetWithFaults(name="Flat", faults=[fault("drift", flat, 1, 5)]),
                created_by=creator,
            )


@pytest.mark.asyncio
async def test_faults_are_refused_where_they_could_not_be_labelled(sessions):
    creator, view = await source(sessions)
    flat, wave = (item.id for item in view.series)
    async with sessions() as session:
        await DojoLabels(session).create(
            view.id, LabelCreate(start_at=at(5), end_at=at(8)), created_by=creator
        )
    refusals = [
        ([fault("step", "nope", 1, 2, 1)], "has no series 'nope'"),
        ([fault("gap", flat, 100, 110)], "holds no values"),
        ([fault("freeze", flat, 7, 9)], "overlaps the label from"),
        (
            [fault("step", flat, 20, 30, 1), fault("gap", wave, 25, 35)],
            "Fault 2 overlaps fault 1",
        ),
    ]
    for faults, message in refusals:
        async with sessions() as session:
            with pytest.raises(ValidationError, match=message):
                await DojoDatasets(session).inject_faults(
                    view.id,
                    DatasetWithFaults(name="Refused", faults=faults),
                    created_by=creator,
                )
            await session.rollback()
    async with sessions() as session:
        listed = await DojoDatasets(session).list(DatasetListQuery())
    assert [item.id for item in listed.items] == [view.id]


def test_a_fault_needs_an_interval_and_a_size_only_where_it_moves_values():
    with pytest.raises(SchemaError, match="end_at must be after start_at"):
        fault("step", "s", 5, 5)
    with pytest.raises(SchemaError, match="A gap takes no size"):
        fault("gap", "s", 1, 2, size=3)
    with pytest.raises(SchemaError, match="needs a time zone"):
        Fault(
            kind="freeze",
            series_id="s",
            start_at=datetime(2024, 1, 1),
            end_at=at(1),
        )
