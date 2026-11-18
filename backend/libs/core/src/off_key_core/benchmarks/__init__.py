"""Public benchmark collections the Dojo can import, with their provenance.

A collection lists its series with everything an import needs to check what
it downloads: the file, its length, where the labelled anomaly lies, how much
of the start is meant for training, and the SHA-256 of the file. Nothing here
fetches anything; the Dojo does that on request.
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import cache
from importlib.resources import files
from typing import Literal

# A benchmark series has positions, not times. The Dojo gives value i the
# instant BENCHMARK_EPOCH + i seconds, so a dataset still replays in time order.
BENCHMARK_EPOCH = datetime(2021, 1, 1, tzinfo=UTC)
BENCHMARK_STEP = timedelta(seconds=1)
Variant = Literal["original", "distorted", "noise"]


@dataclass(frozen=True)
class Collection:
    id: str
    name: str
    description: str
    authors: str
    citation: str
    url: str
    license: str
    mirror: str


@dataclass(frozen=True)
class Series:
    id: str
    collection: str
    number: int
    name: str
    domain: str
    variant: Variant
    points: int
    train_points: int
    # Positions of the first and last anomalous value, counted from 0.
    anomaly_first: int
    anomaly_last: int
    file: str
    sha256: str

    @property
    def train_holds_anomaly(self) -> bool:
        """The archive's own training part reaches into the anomaly.

        Only series 203 does; use the values before ``anomaly_first`` to train.
        """
        return self.train_points > self.anomaly_first

    def instant(self, position: int) -> datetime:
        return BENCHMARK_EPOCH + position * BENCHMARK_STEP


UCR = Collection(
    id="ucr-anomaly-2021",
    name="UCR Time Series Anomaly Archive",
    description=(
        "250 univariate series from medicine, biology, industry and space, "
        "each with exactly one labelled anomaly in its test part. Collected "
        "to replace benchmarks whose anomalies are trivial or mislabelled."
    ),
    authors="Renjie Wu and Eamonn J. Keogh",
    citation=(
        'R. Wu and E. J. Keogh, "Current Time Series Anomaly Detection '
        'Benchmarks are Flawed and are Creating the Illusion of Progress," '
        "IEEE Transactions on Knowledge and Data Engineering, 2021, "
        "doi:10.1109/TKDE.2021.3112126"
    ),
    url="https://www.cs.ucr.edu/~eamonn/time_series_data_2018/",
    license=(
        "Published openly for benchmarking without a stated licence; "
        "the authors ask to be cited."
    ),
    # The KDD Cup 2021 files as TSB-UAD redistributes them, at a pinned
    # revision; every file is checked against its SHA-256 below.
    mirror=(
        "https://huggingface.co/datasets/AutonLab/Timeseries-PILE/resolve/"
        "ea89753da2b451928436adb333c7a2e892461c7d/anomaly_detection/"
        "TSB-UAD-Public/KDD21/"
    ),
)

# Where each series was recorded, from the source names the archive keeps.
DOMAINS = (
    (r"InternalBleeding|CHARIS|tilt", "Blood pressure"),
    (r"resperation", "Respiration"),
    (r"gait|GP711Marker|Walking|weallwalk|park3m|taichidb", "Gait and motion"),
    (r"insectEPG|Lab2Cmac", "Insect behaviour"),
    (r"PowerDemand|powerdemand", "Power demand"),
    (r"CIMIS", "Air temperature"),
    (r"MARS", "Spacecraft"),
    (r"Mesoplodon", "Whale movement"),
    (r".", "ECG"),
)


def _domain(name: str) -> str:
    return next(label for pattern, label in DOMAINS if re.search(pattern, name))


@cache
def ucr_series() -> tuple[Series, ...]:
    text = files("off_key_core").joinpath("benchmarks/ucr_anomaly_2021.json")
    table = json.loads(text.read_text())
    columns = table["columns"]
    items = []
    for row in table["series"]:
        item = dict(zip(columns, row, strict=True))
        number, name = item["number"], item["name"]
        variant: Variant = (
            "distorted"
            if name.startswith("DISTORTED")
            else "noise"
            if name.startswith("NOISE")
            else "original"
        )
        source = re.sub(r"^(DISTORTED|NOISE)", "", name)
        # The archive names a series by its training end and the anomaly's
        # first and last position, the end counted exclusively in these files.
        items.append(
            Series(
                id=f"ucr-{number:03d}",
                collection=UCR.id,
                number=number,
                name=source,
                domain=_domain(source),
                variant=variant,
                points=item["points"],
                train_points=item["train"],
                anomaly_first=item["start"],
                anomaly_last=max(item["end"] - 1, item["start"]),
                file=(
                    f"{number:03d}_UCR_Anomaly_{name}_{item['train']}_"
                    f"{item['start']}_{item['end']}.out"
                ),
                sha256=item["sha256"],
            )
        )
    return tuple(items)


def collections() -> tuple[Collection, ...]:
    return (UCR,)


def collection(collection_id: str) -> Collection | None:
    return next((item for item in collections() if item.id == collection_id), None)


def series(series_id: str) -> Series | None:
    return _by_id().get(series_id)


@cache
def _by_id() -> dict[str, Series]:
    return {item.id: item for item in ucr_series()}


def search(
    text: str = "", domain: str | None = None, variant: Variant | None = None
) -> list[Series]:
    """Series whose number, name or domain contains every word of ``text``."""
    words = text.casefold().split()
    found = []
    for item in ucr_series():
        if domain and item.domain != domain:
            continue
        if variant and item.variant != variant:
            continue
        haystack = f"ucr {item.number:03d} {item.name} {item.domain} {item.variant}"
        if all(word in haystack.casefold() for word in words):
            found.append(item)
    return found


def domains() -> list[str]:
    return sorted({item.domain for item in ucr_series()})
