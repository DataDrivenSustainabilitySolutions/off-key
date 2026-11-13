"""Dojo datasets as the gateway, TACTIC, the web app and agents see them."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .pipelines import PipelineDefinition, PipelineNodePreview

# One dataset stays a size a single comparison run can replay quickly.
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_DATASET_POINTS = 5_000_000
MAX_DATASET_SERIES = 64
MAX_POINTS_PAGE = 10_000
# Runs replay on the Dojo worker; more than this many waiting is refused.
MAX_ACTIVE_RUNS = 20
MAX_RESULTS_PAGE = 10_000
# A run's results are drawn from at most this many stretches of time.
MAX_OUTLINE_BUCKETS = 2_000
# A run keeps fewer observations than this with the values at every step.
MAX_STEP_SAMPLES = 24
MAX_DATASET_LABELS = 500
# Recorded alarms read for label suggestions, and suggestions returned.
MAX_SUGGESTION_ALARMS = 50_000
MAX_LABEL_SUGGESTIONS = 200
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
    """How series sampled at different moments combine into one input.

    The rules a live monitor applies, measured in the data's own time: each
    series' last value counts for ``hold_intervals`` of that series' usual
    interval, and never for less than ``minimum_hold_seconds``.
    """

    hold_intervals: float = Field(default=3.0, ge=1, le=1000)
    minimum_hold_seconds: float = Field(default=30.0, gt=0, le=7 * 86400)


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
    compare_calibration: bool = Field(
        default=False,
        description="Also try every other calibration method on the run's "
        "detector scores, for `GET /v1/dojo/runs/{run_id}/calibration`. The "
        "replay takes longer. A design whose detection rule is the conformal "
        "martingale has no boundary on its scores and is refused.",
    )


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
    compares_calibration: bool = Field(
        default=False,
        description="The run also tries the other calibration methods on its "
        "scores; `GET /v1/dojo/runs/{run_id}/calibration` compares them.",
    )


class RunView(RunSummary):
    definition: dict[str, Any] = Field(description="The compiled design.")
    bindings: list[RunBinding]
    alignment: RunAlignment
    cancel_requested: bool
    stats: dict[str, int] = Field(
        description="Points that formed no observation, by reason, for "
        "example 'missing_reading' or 'waiting_for_reading'."
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


class RunOutlineQuery(DojoModel):
    buckets: int = Field(
        default=300,
        ge=1,
        le=MAX_OUTLINE_BUCKETS,
        description="How many equal stretches of time the results are summed "
        "up in, for example one per pixel column of a chart.",
    )


class OutlineBucket(DojoModel):
    """The results of one stretch of time."""

    start_at: datetime
    results: int
    score_min: float | None = Field(
        description="The lowest and the highest score in the stretch, read "
        "like a result's 'score'; null where nothing was scored yet."
    )
    score_max: float | None
    threshold_min: float | None = Field(
        description="The lowest and the highest alarm threshold in the "
        "stretch; null where the results carry none."
    )
    threshold_max: float | None
    alarms: int = Field(description="How many of the results alarmed.")


class RunOutline(DojoModel):
    """A run's results summed up over equal stretches of time."""

    run_id: str
    strategy: str
    start_at: datetime | None = Field(
        description="When the first and the last result were scored; null for "
        "a run without results."
    )
    end_at: datetime | None
    bucket_seconds: float = Field(description="How long one stretch is.")
    buckets: list[OutlineBucket] = Field(
        max_length=MAX_OUTLINE_BUCKETS,
        description="The stretches that hold results, in time order.",
    )


class StepSample(DojoModel):
    """What one observation of a run looked like at every step."""

    sequence: int = Field(description="The result this observation gave.")
    timestamp: datetime
    phase: str
    steps: dict[str, PipelineNodePreview] = Field(
        description="By step: the values that went in and came out, at most "
        "the first eight features of each, and why a step gave none."
    )


class RunSteps(DojoModel):
    """A few observations of a run, spread from its first result to its last."""

    run_id: str
    samples: list[StepSample] = Field(
        max_length=MAX_STEP_SAMPLES,
        description="In time order; empty until the run has ended.",
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


class LabelBatch(DojoModel):
    """Add several labels at once, for example every suggestion of a dataset."""

    labels: list[LabelCreate] = Field(min_length=1, max_length=MAX_LABEL_SUGGESTIONS)


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


class LabelSuggestionQuery(DojoModel):
    gap_seconds: float = Field(
        default=600.0,
        ge=0,
        le=7 * 86400,
        description="Recorded alarms closer together than this form one suggestion.",
    )


class LabelSuggestion(DojoModel):
    """Recorded alarms of live monitors that could mark a known problem."""

    start_at: datetime = Field(description="The first alarm of the episode.")
    end_at: datetime = Field(
        description="The last alarm, or one second after a lone alarm, so the "
        "interval can become a label as it is."
    )
    alarm_count: int
    monitor_ids: list[str] = Field(
        description="Monitors that raised the alarms; empty for alarms "
        "recorded without one."
    )
    reading_ids: list[str] = Field(
        description="The dataset's catalogue readings the alarms were about."
    )


class LabelSuggestionList(DojoModel):
    """Alarms that live monitors recorded on the readings a dataset was copied
    from, inside its time span, grouped into episodes. Empty for uploads."""

    items: list[LabelSuggestion] = Field(
        max_length=MAX_LABEL_SUGGESTIONS, description="Ordered by start_at."
    )
    truncated: bool = Field(
        description="More alarms or episodes were recorded than are suggested; "
        "the earliest are returned."
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


class MethodMetrics(DojoModel):
    """One calibration method on the detector scores of one run."""

    method: str = Field(description="'fixed_split', or an adapting method's id.")
    name: str
    family: Literal["fixed", "conformal", "bayesian"]
    own: bool = Field(
        description="The run's own calibration step, with the settings of the "
        "design. Every other method ran with its defaults."
    )
    failed: str | None = Field(
        description="Why the method stopped on these scores. Its counts then "
        "cover only the results before it stopped, and it has no share or "
        "rate, which would be over results it never judged."
    )
    alarm_count: int = Field(description="Results on which the method alarmed.")
    alarm_share: float | None = Field(
        description="alarm_count over the results the methods judged."
    )
    labels_scored: int = Field(
        description="Labels the run scored; a method that stopped may not "
        "have reached all of them."
    )
    labels_detected: int
    detection_rate: float | None
    median_delay_seconds: float | None
    false_alarms: int = Field(description="Alarm onsets outside every label.")
    false_alarms_per_day: float | None


class MethodComparison(DojoModel):
    """Calibration methods side by side on one finished run.

    Every method saw the same detector scores in the same order: first the
    calibration window, then each scored observation. They share one alarm
    rate and one number of exceedances in a row, so only the method differs.
    """

    run_id: str
    run_name: str
    alpha: float = Field(description="The alarm rate every method aimed at.")
    consecutive: int = Field(
        description="Scores above the boundary in a row that raise an alarm."
    )
    results: int = Field(description="Results the methods judged.")
    scored_from: datetime | None = Field(
        description="First result the methods judged; the run's own step "
        "started there too."
    )
    scored_to: datetime | None
    labels_total: int
    evaluated_seconds: float = Field(
        description="Judged time outside every label, the base of the rates."
    )
    methods: list[MethodMetrics] = Field(
        max_length=64, description="The run's own step first."
    )


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
