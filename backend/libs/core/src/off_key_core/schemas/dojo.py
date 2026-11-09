"""Dojo datasets as the gateway, TACTIC, the web app and agents see them."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .pipelines import PipelineDefinition

# One dataset stays a size a single comparison run can replay quickly.
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_DATASET_POINTS = 5_000_000
MAX_DATASET_SERIES = 64
MAX_POINTS_PAGE = 10_000
# Runs replay on the Dojo worker; more than this many waiting is refused.
MAX_ACTIVE_RUNS = 20
MAX_RESULTS_PAGE = 10_000
MAX_DATASET_LABELS = 500
# A comparison puts this many runs on one dataset side by side; each run keeps
# its own colour in the chart beside two series of values.
MAX_COMPARED_RUNS = 6
DatasetOrigin = Literal["csv", "history"]
RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
CsvLayout = Literal["wide", "long"]
LabelOutcomeKind = Literal["detected", "missed", "unscored"]


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


def _aware(value: datetime | None, name: str) -> None:
    if value is not None and value.tzinfo is None:
        raise ValueError(f"{name} needs a time zone, for example Z")


class DatasetFromHistory(DojoModel):
    """Copy recorded readings for one time window into a new dataset."""

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    reading_ids: list[str] = Field(min_length=1, max_length=MAX_DATASET_SERIES)
    start: datetime | None = Field(
        default=None,
        description="Omit to copy everything stored, from the first recorded value.",
    )
    end: datetime

    @model_validator(mode="after")
    def window(self):
        _aware(self.start, "start")
        _aware(self.end, "end")
        if self.start is not None and self.end <= self.start:
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


class RunAlignment(DojoModel):
    """How readings sampled at different instants combine into one input.

    The same rules a live monitor applies, measured in the data's own time:
    a value older than ``freshness_seconds`` no longer counts, and readings
    further apart than ``max_skew_seconds`` do not form one observation.
    """

    freshness_seconds: float = Field(default=30.0, gt=0, le=7 * 86400)
    max_skew_seconds: float = Field(default=5.0, ge=0, le=7 * 86400)


class RunCreate(DojoModel):
    """Replay one detection design over one dataset."""

    dataset_id: str
    name: str = Field(default="", max_length=120)
    definition: PipelineDefinition = Field(
        description="The design, as the pipeline library stores a draft."
    )
    bindings: dict[str, str] = Field(
        min_length=1,
        max_length=MAX_DATASET_SERIES,
        description="Each input slot id of the design, mapped to a series id "
        "of the dataset.",
    )
    alignment: RunAlignment = Field(default_factory=RunAlignment)


class RunBinding(DojoModel):
    slot_id: str
    series_id: str
    series_name: str


class RunSummary(DojoModel):
    id: str
    dataset_id: str
    name: str
    status: RunStatus
    strategy: str
    points_total: int
    points_read: int
    result_count: int
    alarm_count: int
    error: str | None
    created_by: int | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunView(RunSummary):
    definition: dict[str, Any] = Field(description="The compiled design.")
    bindings: list[RunBinding]
    alignment: RunAlignment
    cancel_requested: bool
    stats: dict[str, int] = Field(
        description="Observations that produced no result, by reason, for "
        "example 'waiting_for_all' or 'observation_skew_block'."
    )


class RunListPage(DojoModel):
    items: list[RunSummary] = Field(max_length=100)
    next_offset: int | None = None


class RunListQuery(DojoModel):
    dataset_id: str | None = None
    status: RunStatus | None = None
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class RunResultsQuery(DojoModel):
    after: int | None = Field(
        default=None, ge=0, description="Return results after this sequence."
    )
    alarm: bool | None = Field(
        default=None,
        description="true returns only results that alarmed, for example to "
        "mark alarms on a chart without reading every result.",
    )
    limit: int = Field(default=2000, ge=1, le=MAX_RESULTS_PAGE)


class RunResult(DojoModel):
    sequence: int
    timestamp: datetime
    phase: str = Field(
        description="What the detector did, for example 'collecting', "
        "'warmup' or 'ready'/'operational' once it scores."
    )
    score: float | None = Field(
        description="The p-value for a static baseline (lower is more unusual) "
        "or the anomaly score for an adaptive stream (higher is more unusual); "
        "null while the detector is still learning."
    )
    threshold: float | None = Field(
        description="The alarm threshold of an adaptive score; null for a "
        "static baseline, which alarms on a martingale over its p-values."
    )
    alarm: bool


class RunResultsPage(DojoModel):
    items: list[RunResult] = Field(max_length=MAX_RESULTS_PAGE)
    next_after: int | None = Field(
        default=None, description="Pass as 'after' to read the next page."
    )


class RunPromote(DojoModel):
    """Save a run's design as a template in the pipeline library."""

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class PromotedBinding(DojoModel):
    slot_id: str
    slot_label: str
    series_name: str
    reading_id: str | None = Field(
        description="Catalogue reading the bound series was copied from, the "
        "suggested live input for this slot; null for an uploaded series."
    )


class RunPromotion(DojoModel):
    pipeline_id: str = Field(description="The new template in the library.")
    pipeline_name: str
    bindings: list[PromotedBinding] = Field(max_length=MAX_DATASET_SERIES)


class LabelCreate(DojoModel):
    """Mark a known problem as the interval from ``start_at`` to ``end_at``."""

    start_at: datetime
    end_at: datetime
    note: str = Field(
        default="",
        max_length=500,
        description="What happened, for example 'bearing fault, replaced'.",
    )

    @model_validator(mode="after")
    def interval(self):
        _aware(self.start_at, "start_at")
        _aware(self.end_at, "end_at")
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class LabelChange(DojoModel):
    start_at: datetime | None = None
    end_at: datetime | None = None
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def interval(self):
        _aware(self.start_at, "start_at")
        _aware(self.end_at, "end_at")
        return self


class LabelView(DojoModel):
    id: str
    dataset_id: str
    start_at: datetime
    end_at: datetime
    note: str
    created_by: int | None
    created_at: datetime


class LabelList(DojoModel):
    items: list[LabelView] = Field(
        max_length=MAX_DATASET_LABELS, description="Ordered by start_at."
    )


class LabelOutcome(DojoModel):
    label_id: str
    start_at: datetime
    end_at: datetime
    outcome: LabelOutcomeKind = Field(
        description="'detected' if the run alarmed inside the interval, "
        "'missed' if it scored the interval without alarming, and 'unscored' "
        "if the run produced no score during it, for example because the "
        "detector was still learning."
    )
    first_alarm_at: datetime | None
    delay_seconds: float | None = Field(
        description="From the start of the label to the first alarm inside it."
    )


class RunMetrics(DojoModel):
    """Event metrics of one finished run against its dataset's labels.

    A label is one event: alarming once inside it detects it. Alarms outside
    every label count as false alarms, once per onset, so an alarm held over
    many consecutive results is one false alarm.
    """

    run_id: str
    run_name: str
    strategy: str
    scored_from: datetime | None = Field(
        description="First result with a score; nothing before it can alarm."
    )
    scored_to: datetime | None = Field(description="Last result of the run.")
    labels_total: int
    labels_scored: int = Field(description="Labels the run produced scores for.")
    labels_detected: int
    detection_rate: float | None = Field(
        description="labels_detected / labels_scored; null without scored labels."
    )
    median_delay_seconds: float | None
    max_delay_seconds: float | None
    alarm_count: int = Field(description="Results with an alarm, inside or outside.")
    false_alarms: int = Field(description="Alarm onsets outside every label.")
    evaluated_seconds: float = Field(
        description="Scored time outside every label, the base of the rate."
    )
    false_alarms_per_day: float | None = Field(
        description="false_alarms per 24 hours of evaluated time; null when "
        "no time outside the labels was scored."
    )
    labels: list[LabelOutcome] = Field(max_length=MAX_DATASET_LABELS)


class ComparisonQuery(DojoModel):
    run_ids: list[str] = Field(
        min_length=1,
        max_length=MAX_COMPARED_RUNS,
        description="Finished runs on this dataset; repeat the parameter.",
    )

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.run_ids)) != len(self.run_ids):
            raise ValueError("Each run may appear only once")
        return self


class Comparison(DojoModel):
    dataset_id: str
    labels: list[LabelView] = Field(max_length=MAX_DATASET_LABELS)
    runs: list[RunMetrics] = Field(max_length=MAX_COMPARED_RUNS)
