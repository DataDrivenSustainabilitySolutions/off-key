"""Benchmark collections: the catalogue, labelled CSV columns and imports."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from off_key_core import benchmarks
from off_key_core.db.models import (
    DeploymentMaintenance,
    DojoDataset,
    DojoLabel,
    DojoPoint,
    DojoRun,
    DojoRunResult,
    DojoSeries,
    User,
)
from off_key_core.schemas.dojo import (
    BenchmarkImport,
    BenchmarkListQuery,
    CsvImportQuery,
    DatasetWithFaults,
    Fault,
)
from off_key_tactic_middleware.domain import NotFoundError, ValidationError
from off_key_tactic_middleware.services.dojo import benchmarks as service_module
from off_key_tactic_middleware.services.dojo.benchmarks import (
    DojoBenchmarks,
    parse_values,
)
from off_key_tactic_middleware.services.dojo.csv_import import LabelRuns, read_points
from off_key_tactic_middleware.services.dojo.datasets import DojoDatasets
from off_key_tactic_middleware.services.dojo.labels import dataset_labels
from pydantic import ValidationError as SchemaError
from sqlalchemy import func, select

from tests.support.env import set_auth_env
from tests.support.gateway import gateway_app
from tests.support.http import asgi_client
from tests.support.membership import bootstrap
from tests.support.tokens import access_token

T0 = datetime(2026, 3, 1, tzinfo=UTC)
EPOCH = benchmarks.BENCHMARK_EPOCH


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------


def test_the_ucr_catalogue_lists_every_series_once_with_a_checkable_file():
    series = benchmarks.ucr_series()
    assert len(series) == 250
    assert len({item.id for item in series}) == 250
    assert [item.number for item in series] == list(range(1, 251))
    for item in series:
        assert len(item.sha256) == 64
        assert item.file.startswith(f"{item.number:03d}_UCR_Anomaly_")
        assert 0 < item.anomaly_first <= item.anomaly_last < item.points
    # The anomaly lies after the training part, except in one known flaw.
    assert [item.id for item in series if item.train_holds_anomaly] == ["ucr-203"]


def test_series_are_read_from_the_archive_file_name():
    item = benchmarks.series("ucr-112")
    assert item is not None
    assert (item.name, item.domain, item.variant) == ("BIDMC1", "ECG", "original")
    assert (item.points, item.train_points) == (11000, 2500)
    # 5400 to 5600 in the name: the end is exclusive.
    assert (item.anomaly_first, item.anomaly_last) == (5400, 5599)
    # A single-value anomaly keeps its one position.
    lone = benchmarks.series("ucr-187")
    assert lone is not None
    assert lone.anomaly_first == lone.anomaly_last == 168250
    distorted = benchmarks.series("ucr-004")
    assert distorted is not None
    assert (distorted.name, distorted.variant) == ("BIDMC1", "distorted")


def test_search_needs_every_word_and_filters_by_domain_and_variant():
    assert [item.id for item in benchmarks.search("bidmc original")] == ["ucr-112"]
    power = benchmarks.search(domain="Power demand", variant="original")
    assert {item.name for item in power} == {
        "PowerDemand1",
        "PowerDemand2",
        "PowerDemand3",
        "PowerDemand4",
        "Italianpowerdemand",
    }
    assert benchmarks.search("no such series") == []
    assert "ECG" in benchmarks.domains()


def body_of(values: list[float], labels: list[int]) -> bytes:
    return "".join(
        f"{value},{float(label)}\n" for value, label in zip(values, labels, strict=True)
    ).encode()


def fake_series(values: list[float], anomaly: tuple[int, int], train: int = 4):
    body = body_of(values, [0] * len(values))
    item = replace(
        benchmarks.series("ucr-112"),
        points=len(values),
        train_points=train,
        anomaly_first=anomaly[0],
        anomaly_last=anomaly[1],
        sha256=hashlib.sha256(body).hexdigest(),
    )
    return item, body


def test_a_download_must_match_the_catalogue():
    item, body = fake_series([1.0, 2.0, 3.0], (2, 2), train=1)
    assert parse_values(body, item) == [1.0, 2.0, 3.0]
    with pytest.raises(ValidationError, match="does not match"):
        parse_values(body + b"4,0\n", item)
    short = replace(item, points=4)
    with pytest.raises(ValidationError, match="not the 4 expected"):
        parse_values(body, short)


# ---------------------------------------------------------------------------
# A label column in a CSV
# ---------------------------------------------------------------------------


def stamp(second: int) -> str:
    return (T0 + timedelta(seconds=second)).isoformat()


def test_a_label_column_becomes_one_interval_per_marked_run():
    rows = [(0, 1, 0), (1, 2, 1), (2, 3, 1), (3, 4, 0), (4, 5, "true"), (5, 6, 1)]
    body = "time,value,anomaly\n" + "".join(
        f"{stamp(t)},{value},{mark}\n" for t, value, mark in rows
    )
    labels = LabelRuns()
    declared, points = read_points(
        body.encode(), CsvImportQuery(name="x", label_column="anomaly"), labels
    )
    assert declared == ["value"]
    assert [value for _, _, value in points] == [1, 2, 3, 4, 5, 6]
    seconds = [
        (int((start - T0).total_seconds()), int((end - T0).total_seconds()))
        for start, end in labels.intervals
    ]
    # Still marked at the last row: the run ends there.
    assert seconds == [(1, 2), (4, 5)]


@pytest.mark.parametrize(
    "rows, message",
    [
        ([(0, 1, 2)], "not 0 or 1"),
        ([(5, 1, 0), (4, 2, 1)], "time order"),
    ],
)
def test_a_label_column_holds_marks_in_time_order(rows, message):
    body = "time,value,anomaly\n" + "".join(
        f"{stamp(t)},{value},{mark}\n" for t, value, mark in rows
    )
    labels = LabelRuns()
    _, points = read_points(
        body.encode(), CsvImportQuery(name="x", label_column="anomaly"), labels
    )
    with pytest.raises(ValidationError, match=message):
        list(points)


def test_a_label_column_needs_the_wide_layout():
    with pytest.raises(SchemaError, match="wide"):
        CsvImportQuery(name="x", layout="long", label_column="anomaly")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def dojo_database(member_database, monkeypatch):
    set_auth_env(monkeypatch)
    engine, sessions = member_database
    async with engine.begin() as connection:
        for table in (
            DeploymentMaintenance,
            DojoDataset,
            DojoSeries,
            DojoPoint,
            DojoLabel,
            DojoRun,
            DojoRunResult,
        ):
            await connection.run_sync(table.__table__.create)
    return sessions


@pytest.mark.asyncio
async def test_a_csv_label_column_is_stored_as_labels(dojo_database):
    creator = await bootstrap(dojo_database)
    body = "time,value,anomaly\n" + "".join(
        f"{stamp(t)},{t},{1 if t in (3, 6, 7) else 0}\n" for t in range(10)
    )
    async with dojo_database() as session:
        view = await DojoDatasets(session).import_csv(
            body.encode(),
            CsvImportQuery(name="Pump", label_column="anomaly"),
            created_by=creator,
        )
        labels = await dataset_labels(session, view.id)
    assert [item.name for item in view.series] == ["value"]
    assert view.source["label_column"] == "anomaly"
    # One marked row lasts a millisecond, so it covers that value only.
    assert [(item.start_at, item.end_at) for item in labels] == [
        (T0 + timedelta(seconds=3), T0 + timedelta(seconds=3, milliseconds=1)),
        (T0 + timedelta(seconds=6), T0 + timedelta(seconds=7)),
    ]
    assert {item.created_by for item in labels} == {creator}


def values_with_anomaly(points: int = 12) -> list[float]:
    return [float(i % 3) for i in range(points)]


@pytest.mark.asyncio
async def test_a_series_is_imported_once_with_its_anomaly_as_a_label(
    dojo_database, monkeypatch
):
    creator = await bootstrap(dojo_database)
    item, body = fake_series(values_with_anomaly(), (7, 9))
    monkeypatch.setattr(benchmarks, "series", lambda series_id: item)
    asked = []

    def fetch(url: str) -> bytes:
        asked.append(url)
        return body

    async with dojo_database() as session:
        first = await DojoBenchmarks(session, fetch).import_series(
            BenchmarkImport(series_ids=["ucr-112"]), created_by=creator
        )
    async with dojo_database() as session:
        again = await DojoBenchmarks(session, fetch).import_series(
            BenchmarkImport(series_ids=["ucr-112"]), created_by=creator
        )
        dataset = await DojoDatasets(session).get(first.items[0].id)
        labels = await dataset_labels(session, dataset.id)
        listed = await DojoBenchmarks(session, fetch).list(
            BenchmarkListQuery(text="ucr 112 bidmc")
        )
    assert asked == [benchmarks.UCR.mirror + item.file]
    assert (first.imported, again.imported) == (1, 0)
    assert again.items[0].id == first.items[0].id
    assert dataset.origin == "benchmark"
    assert dataset.name == "UCR 112 · BIDMC1"
    assert "Eamonn J. Keogh" in dataset.description
    assert dataset.point_count == 12
    assert (dataset.start_at, dataset.end_at) == (
        EPOCH,
        EPOCH + timedelta(seconds=11),
    )
    assert dataset.source["series"] == "ucr-112"
    assert dataset.source["train_points"] == 4
    assert dataset.source["train_end_at"] == (EPOCH + timedelta(seconds=4)).isoformat()
    assert dataset.source["sha256"] == item.sha256
    assert [(label.start_at, label.end_at) for label in labels] == [
        (EPOCH + timedelta(seconds=7), EPOCH + timedelta(seconds=9))
    ]
    assert listed.total == 1
    assert listed.items[0].dataset_id == first.items[0].id
    assert listed.collections[0].citation.startswith("R. Wu and E. J. Keogh")


@pytest.mark.asyncio
async def test_a_copy_with_faults_is_not_taken_for_the_import(
    dojo_database, monkeypatch
):
    creator = await bootstrap(dojo_database)
    item, body = fake_series(values_with_anomaly(), (7, 9))
    monkeypatch.setattr(benchmarks, "series", lambda series_id: item)
    async with dojo_database() as session:
        first = await DojoBenchmarks(session, lambda url: body).import_series(
            BenchmarkImport(series_ids=["ucr-112"]), created_by=creator
        )
        dataset = await DojoDatasets(session).get(first.items[0].id)
        await DojoDatasets(session).inject_faults(
            dataset.id,
            DatasetWithFaults(
                name="With a step",
                faults=[
                    Fault(
                        kind="step",
                        series_id=dataset.series[0].id,
                        start_at=EPOCH + timedelta(seconds=1),
                        end_at=EPOCH + timedelta(seconds=2),
                        size=5,
                    )
                ],
            ),
            created_by=creator,
        )
        await DojoDatasets(session).remove(dataset.id)
    async with dojo_database() as session:
        again = await DojoBenchmarks(session, lambda url: body).import_series(
            BenchmarkImport(series_ids=["ucr-112"]), created_by=creator
        )
        count = await session.scalar(select(func.count()).select_from(DojoDataset))
    assert again.imported == 1
    assert count == 2


@pytest.mark.asyncio
async def test_a_failed_or_unknown_import_leaves_nothing_behind(
    dojo_database, monkeypatch
):
    creator = await bootstrap(dojo_database)
    item, body = fake_series(values_with_anomaly(), (7, 9))
    monkeypatch.setattr(benchmarks, "series", lambda series_id: item)

    def offline(url: str) -> bytes:
        raise OSError("network unreachable")

    async with dojo_database() as session:
        with pytest.raises(ValidationError, match="could not be downloaded"):
            await DojoBenchmarks(session, offline).import_series(
                BenchmarkImport(series_ids=["ucr-112"]), created_by=creator
            )
        with pytest.raises(ValidationError, match="does not match"):
            await DojoBenchmarks(session, lambda url: body + b"1,0\n").import_series(
                BenchmarkImport(series_ids=["ucr-112"]), created_by=creator
            )
    monkeypatch.setattr(benchmarks, "series", lambda series_id: None)
    async with dojo_database() as session:
        with pytest.raises(NotFoundError):
            await DojoBenchmarks(session, lambda url: body).import_series(
                BenchmarkImport(series_ids=["ucr-999"]), created_by=creator
            )
        count = await session.scalar(select(func.count()).select_from(DojoDataset))
    assert count == 0


@pytest.mark.asyncio
async def test_routes_list_and_import_benchmarks(dojo_database, monkeypatch):
    admin = await bootstrap(dojo_database)
    item, body = fake_series(values_with_anomaly(), (7, 9))
    monkeypatch.setattr(benchmarks, "series", lambda series_id: item)
    monkeypatch.setattr(service_module, "fetch_url", lambda url: body)
    async with dojo_database() as session:
        user = await session.get(User, admin)
    headers = {"Authorization": f"Bearer {access_token(user)}"}
    async with asgi_client(gateway_app(sessions=dojo_database)) as client:
        listed = await client.get(
            "/v1/dojo/benchmarks",
            params={"domain": "Power demand", "variant": "original", "limit": 2},
            headers=headers,
        )
        imported = await client.post(
            "/v1/dojo/benchmarks/import",
            json={"series_ids": ["ucr-112"]},
            headers=headers,
        )
        twice = await client.post(
            "/v1/dojo/benchmarks/import",
            json={"series_ids": ["ucr-112", "ucr-112"]},
            headers=headers,
        )
    assert listed.status_code == 200, listed.text
    # Four PowerDemand series and three of Italian power demand.
    assert listed.json()["total"] == 7
    assert listed.json()["next_offset"] == 2
    assert imported.status_code == 201, imported.text
    assert imported.json()["items"][0]["origin"] == "benchmark"
    assert twice.status_code == 422
