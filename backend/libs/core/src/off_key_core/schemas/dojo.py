"""Dojo datasets as the gateway, TACTIC, the web app and agents see them."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# One dataset stays a size a single comparison run can replay quickly.
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_DATASET_POINTS = 5_000_000
MAX_DATASET_SERIES = 64
MAX_POINTS_PAGE = 10_000
DatasetOrigin = Literal["csv", "history"]
CsvLayout = Literal["wide", "long"]


class DojoModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class DatasetSeriesView(DojoModel):
    id: str
    position: int
    name: str
    unit: str | None
    reading_id: str | None = Field(
        description="Catalogue reading the series was copied from, if any."
    )
    point_count: int
    start_at: datetime | None
    end_at: datetime | None


class DatasetSummary(DojoModel):
    id: str
    name: str
    description: str
    origin: DatasetOrigin
    point_count: int
    series_count: int
    start_at: datetime | None
    end_at: datetime | None
    created_by: int | None
    created_at: datetime


class DatasetView(DatasetSummary):
    source: dict[str, Any] = Field(
        description="Provenance: the uploaded file and layout, or the copied "
        "readings and time window."
    )
    series: list[DatasetSeriesView] = Field(max_length=MAX_DATASET_SERIES)


class DatasetListPage(DojoModel):
    items: list[DatasetSummary] = Field(max_length=100)
    next_offset: int | None = None


class DatasetListQuery(DojoModel):
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class CsvImportQuery(DojoModel):
    """How to read an uploaded CSV body; every field has a usable default."""

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    filename: str | None = Field(default=None, max_length=255)
    layout: CsvLayout = Field(
        default="wide",
        description="'wide': one timestamp column and one column per series. "
        "'long': one row per value with series, timestamp and value columns.",
    )
    timestamp_column: str | None = Field(
        default=None,
        max_length=120,
        description="Defaults to the first column ('wide') or 'timestamp' ('long').",
    )
    series_column: str = Field(default="series", max_length=120)
    value_column: str = Field(default="value", max_length=120)
    delimiter: Literal[",", ";", "\t", "|"] | None = Field(
        default=None, description="Detected from the header line when omitted."
    )


class DatasetFromHistory(DojoModel):
    """Copy recorded readings for one time window into a new dataset."""

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    reading_ids: list[str] = Field(min_length=1, max_length=MAX_DATASET_SERIES)
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def window(self):
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("start and end need a time zone, for example Z")
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if len(set(self.reading_ids)) != len(self.reading_ids):
            raise ValueError("Each reading may appear only once")
        return self


class DatasetChange(DojoModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class DatasetPointsQuery(DojoModel):
    after: datetime | None = Field(
        default=None, description="Return points strictly after this instant."
    )
    limit: int = Field(default=2000, ge=1, le=MAX_POINTS_PAGE)


class DatasetPoint(DojoModel):
    timestamp: datetime
    value: float


class DatasetPointsPage(DojoModel):
    items: list[DatasetPoint] = Field(max_length=MAX_POINTS_PAGE)
    next_after: datetime | None = Field(
        default=None, description="Pass as 'after' to read the next page."
    )
