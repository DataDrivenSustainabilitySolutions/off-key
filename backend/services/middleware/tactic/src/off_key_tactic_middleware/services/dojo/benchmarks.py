"""Import series of public benchmark collections as labelled Dojo datasets.

A series is downloaded from the collection's pinned mirror, checked against
the SHA-256 the catalogue records, and stored as one dataset whose labelled
anomaly becomes a label. Importing a series again returns its dataset, so a
setup script or an agent can ask for the same series repeatedly.
"""

import asyncio
import builtins
import hashlib
import math
import os
import urllib.request
from collections.abc import Callable

from off_key_core import benchmarks
from off_key_core.db.models import Agent, DojoDataset
from off_key_core.schemas.dojo import (
    BenchmarkCollectionView,
    BenchmarkImport,
    BenchmarkImportResult,
    BenchmarkListPage,
    BenchmarkListQuery,
    BenchmarkSeriesView,
    DatasetSummary,
)
from sqlalchemy import select

from ...domain import NotFoundError, ValidationError
from .datasets import DojoDatasets

ORIGIN = "benchmark"
# Mirrors are slow at times; a large series is about 20 MB.
FETCH_TIMEOUT_SECONDS = 120
MAX_FILE_BYTES = 64 * 1024 * 1024
MIRROR_ENV = "DOJO_BENCHMARK_MIRROR"

Fetch = Callable[[str], bytes]


def fetch_url(url: str) -> bytes:
    """Read a file over HTTPS, honouring the process's proxy settings."""
    request = urllib.request.Request(url, headers={"User-Agent": "off-key-dojo"})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
        body = response.read(MAX_FILE_BYTES + 1)
    if len(body) > MAX_FILE_BYTES:
        raise ValidationError("The benchmark file is larger than expected")
    return body


def collection_view(item: benchmarks.Collection) -> BenchmarkCollectionView:
    return BenchmarkCollectionView(
        id=item.id,
        name=item.name,
        description=item.description,
        authors=item.authors,
        citation=item.citation,
        url=item.url,
        license=item.license,
        series_count=len(benchmarks.ucr_series()),
        domains=benchmarks.domains(),
    )


def series_view(
    item: benchmarks.Series, dataset_id: str | None = None
) -> BenchmarkSeriesView:
    return BenchmarkSeriesView(
        id=item.id,
        collection=item.collection,
        number=item.number,
        name=item.name,
        domain=item.domain,
        variant=item.variant,
        points=item.points,
        train_points=item.train_points,
        anomaly_first=item.anomaly_first,
        anomaly_last=item.anomaly_last,
        train_holds_anomaly=item.train_holds_anomaly,
        dataset_id=dataset_id,
    )


def parse_values(body: bytes, item: benchmarks.Series) -> list[float]:
    """The series' values: one per line, the first column of 'value,label'."""
    digest = hashlib.sha256(body).hexdigest()
    if digest != item.sha256:
        raise ValidationError(
            f"The downloaded file of {item.id} does not match the catalogue; "
            "the mirror may have changed"
        )
    values = []
    for line in body.decode("ascii").split():
        value = float(line.split(",", 1)[0])
        if not math.isfinite(value):
            raise ValidationError(f"{item.id} holds a value that is not finite")
        values.append(value)
    if len(values) != item.points:
        raise ValidationError(
            f"{item.id} holds {len(values)} values, not the {item.points} expected"
        )
    return values


def description(item: benchmarks.Series, collection: benchmarks.Collection) -> str:
    training = (
        f"The archive marks the first {item.train_points:,} values for "
        f"training, but its anomaly starts at {item.anomaly_first:,}: train on "
        "the values before it."
        if item.train_holds_anomaly
        else f"The first {item.train_points:,} values are for training and "
        "hold no anomaly."
    )
    return (
        f"{collection.name}, series {item.number:03d} ({item.domain}"
        f"{'' if item.variant == 'original' else f', {item.variant} copy'}). "
        f"{training} One value per second stands for each position of the "
        f"original series. By {collection.authors}; cite {collection.citation}."
    )


class DojoBenchmarks:
    def __init__(self, session, fetch: Fetch | None = None):
        self.session = session
        self.fetch = fetch

    async def list(self, query: BenchmarkListQuery) -> BenchmarkListPage:
        found = benchmarks.search(query.text, query.domain, query.variant)
        page = found[query.offset : query.offset + query.limit]
        imported = await self._imported([item.id for item in page])
        end = query.offset + len(page)
        return BenchmarkListPage(
            collections=[collection_view(item) for item in benchmarks.collections()],
            items=[series_view(item, imported.get(item.id)) for item in page],
            total=len(found),
            next_offset=end if end < len(found) else None,
        )

    async def import_series(
        self,
        request: BenchmarkImport,
        *,
        created_by: int | None,
        created_by_agent: Agent | None = None,
    ) -> BenchmarkImportResult:
        items = []
        for series_id in request.series_ids:
            item = benchmarks.series(series_id)
            if item is None:
                raise NotFoundError(f"No benchmark series {series_id!r}")
            items.append(item)
        datasets = DojoDatasets(self.session)
        imported = await self._imported(request.series_ids)
        views = []
        new = 0
        for item in items:
            if item.id in imported:
                view = await datasets.get(imported[item.id])
            else:
                view = await self._import(datasets, item, created_by, created_by_agent)
                new += 1
            views.append(view)
        return BenchmarkImportResult(
            items=[
                DatasetSummary.model_validate(
                    view.model_dump(include=set(DatasetSummary.model_fields))
                )
                for view in views
            ],
            imported=new,
        )

    async def _import(self, datasets, item, created_by, created_by_agent):
        collection = benchmarks.collection(item.collection)
        assert collection is not None
        mirror = os.environ.get(MIRROR_ENV) or collection.mirror
        url = mirror.rstrip("/") + "/" + item.file
        try:
            body = await asyncio.to_thread(self.fetch or fetch_url, url)
        except ValidationError:
            raise
        except Exception as exc:
            raise ValidationError(
                f"{item.id} could not be downloaded from the benchmark mirror: "
                f"{type(exc).__name__}"
            ) from exc
        values = parse_values(body, item)
        return await datasets.import_values(
            f"UCR {item.number:03d} · {item.name}"
            + ("" if item.variant == "original" else f" ({item.variant})"),
            description(item, collection),
            ORIGIN,
            {
                "collection": collection.id,
                "series": item.id,
                "file": item.file,
                "url": url,
                "sha256": item.sha256,
                "train_points": min(item.train_points, item.anomaly_first),
                "train_end_at": item.instant(
                    min(item.train_points, item.anomaly_first)
                ).isoformat(),
                "anomaly_first": item.anomaly_first,
                "anomaly_last": item.anomaly_last,
                "citation": collection.citation,
                "license": collection.license,
            },
            {"value": [(item.instant(i), value) for i, value in enumerate(values)]},
            created_by=created_by,
            created_by_agent=created_by_agent,
            labels=[
                (item.instant(item.anomaly_first), item.instant(item.anomaly_last))
            ],
            label_note=f"Anomaly labelled by {collection.name}",
        )

    async def _imported(self, series_ids: builtins.list[str]) -> dict[str, str]:
        """Each series' oldest import, where it was imported before."""
        if not series_ids:
            return {}
        rows = (
            await self.session.execute(
                select(DojoDataset.id, DojoDataset.source["series"].as_string())
                .where(
                    DojoDataset.origin == ORIGIN,
                    DojoDataset.source["series"].as_string().in_(series_ids),
                    # A copy with faults keeps its source's provenance.
                    DojoDataset.source["copied_from"].as_string().is_(None),
                )
                .order_by(DojoDataset.created_at.desc())
            )
        ).all()
        return {series_id: dataset_id for dataset_id, series_id in rows}
