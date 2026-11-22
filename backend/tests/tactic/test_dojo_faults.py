"""Faults written into a copy of a Dojo dataset, each labelled as a problem."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
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

from tests.support.dojo import create_dojo_tables
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
        await connection.run_sync(create_dojo_tables)
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
async def test_a_size_left_out_is_three_times_the_short_term_noise(sessions):
    creator, view = await source(sessions)
    flat, wave = (item.id for item in view.series)
    async with sessions() as session:
        copy = await DojoDatasets(session).inject_faults(
            view.id,
            DatasetWithFaults(name="Step", faults=[fault("step", wave, 10, 11)]),
            created_by=creator,
        )
    recorded = copy.source["faults"][0]
    # Alternating 0/2 changes by 2 every value: a noise of 2 * 1.4826 / sqrt(2).
    sigma = 2 * 1.4826 / 2**0.5
    assert recorded["sigma"] == pytest.approx(sigma)
    assert recorded["size"] == pytest.approx(3 * sigma)
    assert recorded["sigmas"] == pytest.approx(3)
    async with sessions() as session:
        with pytest.raises(ValidationError, match="does not vary from one value"):
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


async def ramp(factory):
    """One series a minute apart for two hours: 100 plus a 0/1 wobble."""
    creator = await bootstrap(factory)
    rows = "\n".join(f"{at(i).isoformat()},{100 + i % 2}" for i in range(120))
    async with factory() as session:
        view = await DojoDatasets(session).import_csv(
            f"time,level\n{rows}\n".encode(),
            CsvImportQuery(name="Level"),
            created_by=creator,
        )
    return creator, view


async def written(factory, view, creator, faults, **extra):
    async with factory() as session:
        copy = await DojoDatasets(session).inject_faults(
            view.id,
            DatasetWithFaults(name="Shaped", faults=faults, **extra),
            created_by=creator,
        )
    async with factory() as session:
        labels = (await DojoLabels(session).list(copy.id)).items
    return copy, await values(factory, copy.id, copy.series[0].id), labels


@pytest.mark.asyncio
async def test_a_level_fault_comes_in_holds_and_leaves_along_its_envelope(sessions):
    creator, view = await ramp(sessions)
    level = view.series[0].id
    gradual = Fault(
        kind="step",
        series_id=level,
        start_at=at(10),
        end_at=at(30),
        size=10,
        onset_seconds=600,
        recovery="gradual",
        recovery_seconds=300,
    )
    _, value, labels = await written(sessions, view, creator, [gradual])
    base = {i: 100 + i % 2 for i in range(120)}
    # Half way up the ten-minute onset, held, half way down the recovery.
    assert value[at(15)] == pytest.approx(base[15] + 5)
    assert value[at(25)] == pytest.approx(base[25] + 10)
    assert value[at(32)] == pytest.approx(base[32] + 10 * (1 - 2 / 5))
    assert value[at(36)] == base[36]
    assert (labels[0].start_at, labels[0].end_at) == (at(10), at(35))
    assert labels[0].note == (
        "Injected step of +10 (+9.5σ) on level, onset over 10 min, "
        "recovering over 5 min"
    )
    # A drift that never recovers holds its size to the end of the copy.
    lasting = Fault(
        kind="drift",
        series_id=level,
        start_at=at(60),
        end_at=at(70),
        size=-4,
        recovery="none",
    )
    _, value, labels = await written(sessions, view, creator, [lasting])
    assert value[at(65)] == pytest.approx(base[65] - 2)
    assert value[at(119)] == pytest.approx(base[119] - 4)
    assert labels[0].end_at == at(119)
    assert labels[0].note == "Injected drift to -4 (-3.8σ) on level, no recovery"


@pytest.mark.asyncio
async def test_gain_noise_spike_freeze_and_impossible_values(sessions):
    creator, view = await ramp(sessions)
    level = view.series[0].id
    sigma = 1.4826 / 2**0.5

    def make(kind, start, end, **fields):
        return Fault(
            kind=kind, series_id=level, start_at=at(start), end_at=at(end), **fields
        )

    faults = [
        make("gain", 10, 14, sigmas=4),
        make("noise", 20, 49, noise_factor=4, seed=7),
        make("spike", 55, 60, size=50),
        make("freeze", 65, 69, value=0),
        make("out_of_range", 75, 76),
    ]
    _, value, labels = await written(sessions, view, creator, faults)
    # A gain error moves a typical value (100.5) by four times the noise.
    gain = 4 * sigma / 100.5
    assert value[at(12)] == pytest.approx((100 + 0) * (1 + gain))
    # Noise four times as large keeps its mean and repeats from its seed.
    noisy = [value[at(i)] - (100 + i % 2) for i in range(20, 50)]
    assert abs(sum(noisy) / len(noisy)) < 3 * sigma
    assert max(map(abs, noisy)) > sigma
    _, repeated, _ = await written(sessions, view, creator, faults)
    assert [repeated[at(i)] for i in range(20, 50)] == [
        value[at(i)] for i in range(20, 50)
    ]
    # A spike moves one value only.
    assert value[at(55)] == 100 + 1 + 50 and value[at(56)] == 100
    assert [value[at(i)] for i in (65, 69, 70)] == [0, 0, 100]
    # Far beyond anything recorded: the largest value plus ten ranges.
    assert value[at(75)] == 101 + 10 * 1
    assert [item.note for item in labels] == [
        f"Injected gain error moving a typical value by {4 * sigma:+.4g} (+4σ) "
        "on level",
        "Injected noise ×4 on level",
        f"Injected spike of +50 ({50 / sigma:+.2g}σ) on level",
        "Injected freeze at 0 on level",
        "Injected out-of-range value 111 on level",
    ]


@pytest.mark.asyncio
async def test_a_common_mode_fault_moves_several_series_under_one_label(sessions):
    creator, view = await source(sessions)
    flat, wave = (item.id for item in view.series)
    shared = Fault(
        kind="step",
        series_id=wave,
        with_series=[flat],
        start_at=at(10),
        end_at=at(12),
        size=3,
    )
    async with sessions() as session:
        copy = await DojoDatasets(session).inject_faults(
            view.id,
            DatasetWithFaults(name="Both", faults=[shared], end_at=at(30)),
            created_by=creator,
        )
    new_flat, new_wave = (item.id for item in copy.series)
    assert (await values(sessions, copy.id, new_flat))[at(11)] == 13
    assert (await values(sessions, copy.id, new_wave))[at(11)] == 5
    # The copy ends where it was cut.
    assert max(await values(sessions, copy.id, new_flat)) == at(30)
    async with sessions() as session:
        labels = (await DojoLabels(session).list(copy.id)).items
    assert [item.note for item in labels] == [
        "Injected step of +3 (+1.4σ) on wave, flat"
    ]


def test_shapes_and_values_belong_to_the_kinds_that_use_them():
    with pytest.raises(SchemaError, match="A freeze has no onset or recovery"):
        Fault(
            kind="freeze",
            series_id="s",
            start_at=at(0),
            end_at=at(1),
            recovery="gradual",
        )
    with pytest.raises(SchemaError, match="onset_seconds must fit"):
        Fault(
            kind="step", series_id="s", start_at=at(0), end_at=at(1), onset_seconds=61
        )
    with pytest.raises(SchemaError, match="A step takes no value"):
        Fault(kind="step", series_id="s", start_at=at(0), end_at=at(1), value=1)
    with pytest.raises(SchemaError, match="Name each series of a fault once"):
        Fault(
            kind="gap", series_id="s", with_series=["s"], start_at=at(0), end_at=at(1)
        )
