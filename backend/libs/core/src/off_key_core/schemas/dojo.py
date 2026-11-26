"""Dojo datasets as the gateway, TACTIC, the web app and agents see them."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .devices import Autocorrelation, RecentValues, Season, SuggestedLag
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
# Proposed labels waiting for review on one dataset.
MAX_PENDING_LABELS = 1_000
# A comparison puts this many runs on one dataset side by side; each run keeps
# its own colour in the chart beside two series of values.
MAX_COMPARED_RUNS = 6
# Faults one copy of a dataset may carry, each labelled as a known problem.
MAX_FAULTS = 20
MAX_FAULT_COPIES = 20
# A protocol suite writes at most this many values across its copies.
MAX_PROTOCOL_POINTS = 20_000_000
# Benchmark series one import may add; each becomes a dataset of its own.
MAX_BENCHMARK_IMPORT = 20
MAX_BENCHMARK_PAGE = 250
# A benchmark suite holds at most this many datasets; a study runs on each.
MAX_SUITE_DATASETS = 100
# A suite's view lists at most this many studies, the newest.
MAX_SUITE_STUDIES = 100
DatasetOrigin = Literal["csv", "history", "benchmark"]
BenchmarkVariant = Literal["original", "distorted", "noise"]
RunStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
CsvLayout = Literal["wide", "long"]
LabelOutcomeKind = Literal["detected", "missed", "unscored"]
FaultKind = Literal[
    "step", "drift", "gain", "noise", "spike", "freeze", "gap", "out_of_range"
]
FAULT_KINDS: tuple[FaultKind, ...] = (
    "step",
    "drift",
    "gain",
    "noise",
    "spike",
    "freeze",
    "gap",
    "out_of_range",
)
# Kinds whose size moves the values: by `size`, or `sigmas` of the noise.
SIZED_KINDS = ("step", "drift", "gain", "spike")
# Kinds that come in and leave along an envelope.
SHAPED_KINDS = ("step", "drift", "gain")
FaultRecovery = Literal["sudden", "gradual", "none"]
FaultProtocol = Literal["screening-v1", "full-v1"]
FaultPurpose = Literal["practice", "test"]
# Practice seeds lie below this; a test suite's seed is drawn above it.
TEST_SEEDS = 1 << 31


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
    created_by_agent: str | None = Field(
        default=None, description="The agent whose key made the dataset, by name."
    )
    created_at: datetime


class DatasetView(DatasetSummary):
    source: dict[str, Any] = Field(
        description="Provenance: the uploaded file and layout, or the copied "
        "readings and time window. A copy with faults adds `copied_from` and "
        "`faults`."
    )
    series: list[DatasetSeriesView] = Field(max_length=MAX_DATASET_SERIES)


class DatasetListPage(DojoModel):
    items: list[DatasetSummary] = Field(max_length=100)
    next_offset: int | None = None


class DatasetListQuery(DojoModel):
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    mine: bool = Field(
        default=False,
        description="Only what the caller made: a key's own, or the member's own.",
    )


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
    label_column: str | None = Field(
        default=None,
        max_length=120,
        description="'wide' only: a column of 0 and 1 (or false and true) "
        "that marks known anomalies. It is not stored as a series; each run of "
        "rows marked 1 becomes one label of the dataset.",
    )

    @model_validator(mode="after")
    def label_layout(self):
        if self.label_column is not None and self.layout != "wide":
            raise ValueError("A label column needs the 'wide' layout")
        return self


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


class Fault(DojoModel):
    """A problem written into a copy of a series between two times.

    Level faults (step, drift, gain) follow one envelope: from `start_at` they
    grow over `onset_seconds` to their full size, hold until `end_at`, and
    then leave as `recovery` says. A step comes in at once, a drift over the
    whole interval unless `onset_seconds` says otherwise.
    """

    kind: FaultKind = Field(
        description="'step' adds the size, 'drift' ramps up to it, 'gain' "
        "scales the values so that a typical value moves by the size, 'noise' "
        "multiplies the short-term noise by `noise_factor`, 'spike' moves the "
        "first value only, 'freeze' holds the last value before start_at (or "
        "`value`), 'gap' drops the values and 'out_of_range' writes a value "
        "far outside anything recorded (or `value`)."
    )
    series_id: str
    with_series: list[str] = Field(
        default_factory=list,
        max_length=MAX_DATASET_SERIES,
        description="More series that get the same fault at the same time, "
        "under one label: a common-mode fault, such as every phase sagging.",
    )
    start_at: datetime
    end_at: datetime = Field(
        description="The end of the hold; a gradual recovery follows it."
    )
    size: float | None = Field(
        default=None,
        description="For step, drift, gain and spike, in the series' unit. "
        "Left out, `sigmas` of the series' short-term noise.",
    )
    sigmas: float | None = Field(
        default=None,
        description="The size in short-term noise of the series, when `size` "
        "is left out; 3 if both are.",
    )
    onset_seconds: float | None = Field(
        default=None,
        ge=0,
        description="How long a level fault takes to reach full size: 0 for "
        "a step, the whole interval for a drift by default.",
    )
    recovery: FaultRecovery = Field(
        default="sudden",
        description="How a level fault leaves after end_at: at once, "
        "gradually over `recovery_seconds`, or never, to the end of the copy.",
    )
    recovery_seconds: float | None = Field(
        default=None,
        gt=0,
        description="For a gradual recovery; left out, as long as the onset, "
        "or the interval when the onset is sudden.",
    )
    noise_factor: float | None = Field(
        default=None,
        gt=1,
        description="For 'noise': how many times the noise grows; 3 if left out.",
    )
    value: float | None = Field(
        default=None,
        description="For 'freeze', the value it is stuck at, such as 0; for "
        "'out_of_range', the value written.",
    )
    seed: int = Field(default=0, ge=0, description="For 'noise': its draws.")

    @model_validator(mode="after")
    def interval(self):
        _aware(self.start_at, "start_at")
        _aware(self.end_at, "end_at")
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        if (self.size is not None or self.sigmas is not None) and (
            self.kind not in SIZED_KINDS
        ):
            raise ValueError(f"A {self.kind} takes no size")
        shaped = (
            self.onset_seconds is not None
            or self.recovery != "sudden"
            or self.recovery_seconds is not None
        )
        if shaped and self.kind not in SHAPED_KINDS:
            raise ValueError(f"A {self.kind} has no onset or recovery")
        if (
            self.onset_seconds is not None
            and self.onset_seconds > (self.end_at - self.start_at).total_seconds()
        ):
            raise ValueError("onset_seconds must fit between start_at and end_at")
        if self.noise_factor is not None and self.kind != "noise":
            raise ValueError("Only a noise fault takes noise_factor")
        if self.value is not None and self.kind not in ("freeze", "out_of_range"):
            raise ValueError(f"A {self.kind} takes no value")
        if self.series_id in self.with_series or len(set(self.with_series)) != len(
            self.with_series
        ):
            raise ValueError("Name each series of a fault once")
        return self


class DatasetWithFaults(DojoModel):
    """Copy a dataset with faults written in, each labelled as a known problem."""

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    faults: list[Fault] = Field(default_factory=list, max_length=MAX_FAULTS)
    end_at: datetime | None = Field(
        default=None,
        description="Drop the values after this time from the copy, so it "
        "ends a while after its faults.",
    )

    @model_validator(mode="after")
    def ending(self):
        _aware(self.end_at, "end_at")
        return self


class BenchmarkCollectionView(DojoModel):
    id: str
    name: str
    description: str
    authors: str
    citation: str = Field(description="Cite this when you report results.")
    url: str
    license: str
    series_count: int
    domains: list[str]


class BenchmarkSeriesView(DojoModel):
    id: str = Field(description="Pass it to the import, for example 'ucr-112'.")
    collection: str
    number: int
    name: str
    domain: str
    variant: BenchmarkVariant = Field(
        description="'original', or a 'distorted' or 'noise' copy the archive "
        "made harder on purpose."
    )
    points: int
    train_points: int = Field(
        description="The first values, meant for training: free of anomalies."
    )
    anomaly_first: int = Field(description="Position of the first anomalous value.")
    anomaly_last: int = Field(description="Position of the last anomalous value.")
    train_holds_anomaly: bool = Field(
        default=False,
        description="The archive's training part reaches into the anomaly, a "
        "known flaw of a single series: train on the values before it instead.",
    )
    dataset_id: str | None = Field(
        default=None, description="The dataset it was imported as, if it was."
    )


class BenchmarkListQuery(DojoModel):
    text: str = Field(
        default="",
        max_length=200,
        description="Words that must all appear in the number, name, domain or "
        "variant, for example 'ecg 120' or 'power'.",
    )
    domain: str | None = Field(default=None, max_length=60)
    variant: BenchmarkVariant | None = None
    limit: int = Field(default=50, ge=1, le=MAX_BENCHMARK_PAGE)
    offset: int = Field(default=0, ge=0)


class BenchmarkListPage(DojoModel):
    collections: list[BenchmarkCollectionView]
    items: list[BenchmarkSeriesView] = Field(max_length=MAX_BENCHMARK_PAGE)
    total: int = Field(description="Series that match, on every page.")
    next_offset: int | None = None


class BenchmarkImport(DojoModel):
    """Import benchmark series, each as a dataset with its anomaly as a label."""

    series_ids: list[str] = Field(min_length=1, max_length=MAX_BENCHMARK_IMPORT)

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.series_ids)) != len(self.series_ids):
            raise ValueError("Each series may appear only once")
        return self


class BenchmarkImportResult(DojoModel):
    items: list[DatasetSummary] = Field(
        description="One dataset per series, in the order asked. A series "
        "imported before keeps its dataset; it is not imported twice."
    )
    imported: int = Field(description="How many of them are new.")


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


class SeriesShape(DojoModel):
    """A series' course in equal stretches of time: what a chart of it shows."""

    start: datetime
    bucket_seconds: float = Field(description="The time one stretch covers.")
    mean: list[float | None] = Field(
        description="Mean of each stretch; null where it holds no value."
    )
    low: list[float | None] = Field(description="Lowest value of each stretch.")
    high: list[float | None] = Field(description="Highest value of each stretch.")


class SeriesBrief(DojoModel):
    """What a series looks like over time, in a few numbers."""

    series_id: str
    name: str
    count: int = Field(description="Values in the series.")
    first: datetime | None = None
    last: datetime | None = None
    interval_seconds: float | None = Field(
        default=None, description="The usual time between two values."
    )
    values: RecentValues | None = Field(
        default=None,
        description="How the values arrive and move: gaps, spread, quantiles, "
        "noise, flat stretches and, for a state, its levels.",
    )
    level_change: float | None = Field(
        default=None,
        description="How far the level moved from the first tenth of the series "
        "to the last, in spreads. Far from 0, the series is not stationary: a "
        "detector needs the level taken out, or a model that follows it.",
    )
    labelled_shift: float | None = Field(
        default=None,
        description="Mean inside the dataset's labels minus the mean outside, in "
        "spreads. Near 0, the labels do not show in this series' level.",
    )
    shape: SeriesShape | None = None
    persistent: bool | None = Field(
        default=None,
        description="Still strongly correlated twenty steps back: the series "
        "wanders or trends.",
    )
    cycles: list[Season] = Field(
        default_factory=list, description="Repeating cycles, strongest first."
    )
    lags: list[SuggestedLag] = Field(
        default_factory=list,
        description="Lags that carry information of their own, strongest first.",
    )
    notes: list[str] = Field(default_factory=list)


class SeriesProfile(SeriesBrief):
    """What a series looks like over time, so a design can be fitted to it."""

    autocorrelation: list[Autocorrelation] = Field(
        default_factory=list,
        description=(
            "How the series relates to its own past: over its first values, "
            "where a design learns, then over the whole series on a coarser "
            "grid. Empty where too few values vary."
        ),
    )


class SeriesPair(DojoModel):
    """How two series of a dataset move together, on a shared grid of time."""

    first: str = Field(description="Series name.")
    second: str = Field(description="Series name.")
    level: float = Field(
        description="Correlation of the values, from -1 to 1. Two series that "
        "both trend correlate by chance; trust change for that."
    )
    change: float = Field(
        description="Correlation of the changes from one step to the next."
    )
    lead_seconds: float = Field(
        description="Where the changes correlate most, within five steps: "
        "positive when the first series moves before the second, 0 together."
    )
    lead_change: float = Field(description="Correlation of the changes at that lead.")


class LabelCoverage(DojoModel):
    count: int
    labelled_share: float = Field(
        description="Share of the dataset's span inside a label, from 0 to 1."
    )
    median_seconds: float = Field(description="The usual length of a label.")


class DatasetProfile(DojoModel):
    """A whole dataset at a glance: each series, how they move together, and
    where the labels lie. ``profile_series`` has one series' autocorrelation."""

    dataset_id: str
    name: str
    first: datetime | None = None
    last: datetime | None = None
    series: list[SeriesBrief]
    step_seconds: float | None = Field(
        default=None, description="The shared grid that pairs are measured on."
    )
    pairs: list[SeriesPair] = Field(
        default_factory=list,
        description="Pairs that move together (|correlation| of 0.5 or more), "
        "strongest first.",
    )
    labels: LabelCoverage | None = Field(
        default=None, description="Null where the dataset has no label."
    )
    notes: list[str] = Field(default_factory=list)


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
    created_by_agent: str | None = Field(
        default=None, description="The agent whose key queued the run, by name."
    )
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    compares_calibration: bool = Field(
        default=False,
        description="The run also tries the other calibration methods on its "
        "scores; `GET /v1/dojo/runs/{run_id}/calibration` compares them.",
    )
    study_id: str | None = Field(
        default=None, description="The study that queued the run, if any."
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
    mine: bool = Field(
        default=False,
        description="Only what the caller made: a key's own, or the member's own.",
    )


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
    rule: str = Field(
        default="",
        description="The rule that found it, for a label added from a pending "
        "label; empty otherwise.",
    )
    suggested_by_agent: str | None = Field(
        default=None, description="The agent that proposed it, if one did."
    )
    created_by: int | None
    created_at: datetime


class LabelList(DojoModel):
    items: list[LabelView] = Field(
        max_length=MAX_DATASET_LABELS, description="Ordered by start_at."
    )


class PendingLabelView(DojoModel):
    """A proposed label, waiting for a member to add or dismiss it."""

    id: str
    dataset_id: str
    start_at: datetime
    end_at: datetime
    note: str
    rule: str = Field(description="The condition or reasoning that found it.")
    created_by: int | None = Field(description="The member who proposed it.")
    created_by_agent: str | None = Field(description="The agent that proposed it.")
    created_at: datetime


class PendingLabelList(DojoModel):
    items: list[PendingLabelView] = Field(
        max_length=MAX_PENDING_LABELS, description="Ordered by start_at."
    )


class PendingLabelProposal(DojoModel):
    """Propose intervals as labels, for a member to review."""

    labels: list[LabelCreate] = Field(max_length=MAX_LABEL_SUGGESTIONS)
    rule: str = Field(
        default="",
        max_length=500,
        description="How the intervals were chosen, for example 'speed above "
        "3000 while the temperature rose'. Members read it when they review.",
    )
    replace: bool = Field(
        default=False,
        description="Dismiss your own pending labels on the dataset first.",
    )


class LabelRule(DojoModel):
    """Propose a label for every interval where a condition holds."""

    condition: str = Field(
        min_length=1,
        max_length=512,  # the formula parser's limit
        description="A condition over the dataset's series by name, as a Gate "
        "step writes it: `speed > 3000 and temperature > 80`. Write a name that "
        "is not a plain word between backticks. Each series keeps its last value "
        "until its next one.",
    )
    min_duration_seconds: float = Field(
        default=0,
        ge=0,
        le=365 * 86400,
        description="Leave out intervals shorter than this.",
    )
    merge_gap_seconds: float = Field(
        default=0,
        ge=0,
        le=7 * 86400,
        description="Join intervals less than this far apart, before the "
        "shortest are left out.",
    )
    note: str = Field(default="", max_length=500)
    replace: bool = Field(
        default=False,
        description="Dismiss your own pending labels on the dataset first.",
    )


class PendingLabelsMade(DojoModel):
    items: list[PendingLabelView] = Field(
        max_length=MAX_LABEL_SUGGESTIONS, description="The new pending labels."
    )
    skipped: int = Field(description="Intervals left out because they overlap a label.")
    truncated: bool = Field(
        description="The condition held in more intervals than are proposed; "
        "the earliest are kept."
    )
    replaced: int = Field(description="Your earlier pending labels dismissed.")


class PendingLabelChoice(DojoModel):
    """Add a pending label, optionally changed first."""

    id: str
    start_at: datetime | None = None
    end_at: datetime | None = None
    note: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def interval(self):
        _aware(self.start_at, "start_at")
        _aware(self.end_at, "end_at")
        return self


class PendingLabelAccept(DojoModel):
    items: list[PendingLabelChoice] = Field(
        min_length=1, max_length=MAX_LABEL_SUGGESTIONS
    )


class PendingLabelDismiss(DojoModel):
    ids: list[str] = Field(min_length=1, max_length=MAX_PENDING_LABELS)


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
    results: int = Field(default=0, description="Scored results inside the label.")
    chance: float | None = Field(
        default=None,
        description="How likely the run's alarms outside labels, scattered at "
        "random, would hit the label: 1 - (1 - alarm_share) ^ results.",
    )


class ScoreMetrics(DojoModel):
    """How well a run's scores rank labelled results above the rest.

    Threshold-free: they judge the detector's scores, not the alarms its
    calibration and alarm rule made of them. Only scored results count, so a
    run's warm-up is left out. Results are ranked most unusual first: the
    highest anomaly scores, or the lowest p-values of a static baseline.
    """

    scored_results: int
    labelled_results: int = Field(description="Scored results inside a label.")
    pr_auc: float | None = Field(
        description="Average precision of the scores against the labels; "
        "chance level is labelled_results / scored_results."
    )
    auroc: float | None = Field(
        description="Area under the ROC curve; 0.5 is chance. Looks good on "
        "rare anomalies almost by default, so read it beside pr_auc."
    )
    vus_pr: float | None = Field(
        description="Volume under the range-PR surface: PR-AUC against labels "
        "widened by a buffer that fades out over 0 to 50 typical intervals "
        "on each side, averaged over 11 buffer sizes. Forgives scores that "
        "peak just before or after a label."
    )
    top_score_at: datetime | None = Field(
        description="When the most unusual score came, the earliest of equal "
        "ones: the highest score, or a static baseline's lowest p-value."
    )
    top1_hit: bool | None = Field(
        description="With exactly one label: whether the most unusual score lies "
        "within 100 typical intervals of it, as the UCR archive scores a "
        "series. Null with more or fewer labels."
    )
    score_autocorrelation: float | None = Field(
        default=None,
        description="Autocorrelation of the scores 20 results apart. Near 1, "
        "the scores follow a level that moves slowly, so the detector scores "
        "where the series is rather than what is unusual: take time out "
        "before it, with Lags, Change or a forecaster. Null below 40 scored "
        "results or for scores that never change.",
    )


class ScoreFollows(DojoModel):
    series: str = Field(description="An input series of the run.")
    correlation: float = Field(
        description="Rank correlation of the scores with the series' value "
        "at each result, from -1 to 1: positive where higher values score "
        "as more unusual."
    )


class RunDiagnostics(DojoModel):
    """What a run's scores and alarms say without labels.

    Each figure describes the run itself and is safe on data that is not
    stationary: none assumes the scores follow a distribution. ``findings``
    puts in words the ones far enough from the usual to act on.
    """

    results: int = Field(description="Results the run produced.")
    scored_share: float | None = Field(
        description="Share of the results with a score; the rest was warm-up."
    )
    warm_up_seconds: float | None = Field(
        description="From the first result to the first score."
    )
    alarm_share: float | None = Field(
        description="Share of scored results that alarmed."
    )
    alarm_episodes: int = Field(
        description="Separate alarms: runs of consecutive alarming results."
    )
    episodes_per_day: float | None = None
    longest_episode_seconds: float | None = None
    episodes_after_gaps: int = Field(
        description="Episodes that began within five results after a gap in "
        "the data longer than five usual intervals."
    )
    after_gap_share: float | None = Field(
        description="Share of the scored results that lie that close after a "
        "gap: what episodes_after_gaps would be by chance."
    )
    score_trend: float | None = Field(
        default=None,
        description="Rank correlation of the scores with time, from -1 to 1: "
        "positive where the scores grow more unusual over the run.",
    )
    follows: list[ScoreFollows] = Field(
        default_factory=list,
        description="How the scores rank with each input series' value, "
        "strongest first.",
    )
    commonest_score_share: float | None = Field(
        default=None, description="Share of the scores that equal the most common one."
    )
    quick_returns: float | None = Field(
        default=None,
        description="Share of the alarm episodes after the first that begin "
        "within 10 results of the previous one's end. High, the alarm flaps "
        "on and off around its boundary rather than marking separate events. "
        "Null with fewer than two episodes.",
    )
    alarms_alone: int | None = Field(
        default=None,
        description="Only in a comparison of two or more runs: alarm episodes "
        "no other compared run alarmed within 10 usual intervals of. Where "
        "designs disagree is where to look, and label, first. Null outside a "
        "comparison or past 20,000 episodes.",
    )
    findings: list[str] = Field(default_factory=list)


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
    alarm_share: float | None = Field(
        default=None,
        description="Share of scored results outside every label that "
        "alarmed: time in alarm, which an alarm that never stops shows as 1 "
        "where false_alarms shows 1 onset.",
    )
    chance_detections: float | None = Field(
        default=None,
        description="Scored labels an alarm this frequent would hit by chance.",
    )
    adjusted_detection_rate: float | None = Field(
        default=None,
        description="Detections beyond chance: (labels_detected - "
        "chance_detections) / (labels_scored - chance_detections). 0 for "
        "chance and for an alarm that never stops, 1 for every label; null "
        "when chance alone would detect them all.",
    )
    scores: ScoreMetrics | None = Field(
        default=None,
        description="Threshold-free metrics of the scores; null when the run "
        "scored nothing.",
    )
    diagnostics: RunDiagnostics | None = Field(
        default=None,
        description="What the scores and alarms say without labels; null when "
        "they took too long to read.",
    )
    labels: list[LabelOutcome] = Field(max_length=MAX_DATASET_LABELS)


class MethodMetrics(DojoModel):
    """One calibration method on the detector scores of one run."""

    method: str = Field(description="'fixed_split', or an adapting method's id.")
    name: str
    family: Literal["fixed", "conformal", "bayesian", "extreme_value"]
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


class SuiteCreate(DojoModel):
    """Fix labelled datasets as a benchmark suite to test designs on.

    The datasets never change, so every study of the suite is comparable. A
    suite a key makes waits for a member's review before its leaderboard
    counts as reviewed.
    """

    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    dataset_ids: list[str] = Field(min_length=1, max_length=MAX_SUITE_DATASETS)
    derived_from: str | None = Field(
        default=None, description="The suite this one changes, if any."
    )

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.dataset_ids)) != len(self.dataset_ids):
            raise ValueError("Each dataset may appear only once")
        return self


class FaultSuiteCreate(DojoModel):
    """Make a suite of labelled copies of one dataset, each with faults written
    in at reproducible random places.

    Recorded history rarely has labels. Copies with known faults let designs
    be tested on the real background of a setup: the same ``seed`` and
    settings always write the same faults.

    With ``protocol`` the suite follows the fault-injection protocol instead:
    one fault per copy from a fixed grid of shapes, sizes in short-term noise
    and lengths in observations, plus one clean copy without faults, so a
    study reports a detection profile per fault type against a false-alarm
    budget. ``copies``, ``faults_per_copy``, ``kinds`` and ``clean_share``
    are then not used.
    """

    dataset_id: str = Field(
        description="The dataset to copy, such as a setup's history."
    )
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    protocol: FaultProtocol | None = Field(
        default=None,
        description="'screening-v1' (48 faulted copies, for every proposal) or "
        "'full-v1' (about 80, for studies); left out, faults are drawn freely.",
    )
    purpose: FaultPurpose = Field(
        default="practice",
        description="With a protocol: 'practice' to tune on, with your own "
        "seed; 'test' to report on, with a seed the server draws and fault "
        "places kept from keys until a member reviews the suite.",
    )
    warmup_values: int | None = Field(
        default=None,
        ge=1,
        description="With a protocol: observations the design needs before it "
        "scores (its training plus calibration window). Left out, 30% of the "
        "values.",
    )
    window_values: int | None = Field(
        default=None,
        ge=4,
        description="With a protocol: the design's calibration window in "
        "observations, which sets the fault lengths and margins. Left out, 5% "
        "of the values.",
    )
    copies: int = Field(default=8, ge=1, le=MAX_FAULT_COPIES)
    faults_per_copy: int = Field(default=2, ge=1, le=5)
    kinds: list[FaultKind] = Field(
        default_factory=lambda: list(FAULT_KINDS[:2] + FAULT_KINDS[5:7]),
        min_length=1,
        description="The kinds to draw from.",
    )
    series: list[str] = Field(
        default_factory=list,
        description="Names of the series to write faults into; empty means all.",
    )
    clean_share: float = Field(
        default=0.3,
        ge=0,
        le=0.8,
        description="The share of the time span at the start left without "
        "faults, for a design's warm-up.",
    )
    seed: int = Field(
        default=0,
        ge=0,
        lt=TEST_SEEDS,
        description="The same seed writes the same faults. A test suite "
        "ignores it and draws its own.",
    )

    @model_validator(mode="after")
    def distinct(self):
        if len(set(self.kinds)) != len(self.kinds):
            raise ValueError("Each kind may appear only once")
        if self.purpose == "test" and self.protocol is None:
            raise ValueError("A test suite follows a protocol")
        return self


class SuiteChange(DojoModel):
    """Rename or describe a suite; its datasets never change."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class SuiteListQuery(DojoModel):
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    mine: bool = Field(
        default=False,
        description="Only what the caller made: a key's own, or the member's own.",
    )


class SuiteSummary(DojoModel):
    id: str
    name: str
    description: str
    derived_from: str | None
    datasets: int
    studies: int
    created_by: int | None
    created_by_agent: str | None = None
    reviewed: bool = Field(
        description="A member made or reviewed the suite. Only a reviewed "
        "suite's results should back a claim or a proposal."
    )
    created_at: datetime


class SuiteListPage(DojoModel):
    items: list[SuiteSummary] = Field(max_length=100)
    next_offset: int | None = None


class SuiteDataset(DojoModel):
    dataset_id: str
    name: str
    origin: DatasetOrigin
    series_names: list[str] = Field(max_length=MAX_DATASET_SERIES)
    point_count: int
    labels: int = Field(description="Labels of the dataset now.")


class StudyTotals(DojoModel):
    """A study's finished runs taken together.

    Means are over the runs that have the number, which the matching count
    gives: a dataset without labels has no PR-AUC, for example.
    """

    runs_scored: int = Field(description="Finished runs with metrics.")
    labels_scored: int
    labels_detected: int
    detection_rate: float | None
    median_false_alarms_per_day: float | None
    pr_auc: float | None
    pr_auc_runs: int
    vus_pr: float | None
    vus_pr_runs: int
    auroc: float | None
    auroc_runs: int
    top1_hits: int = Field(
        description="Runs on one-label datasets whose most unusual score lay "
        "at the label."
    )
    top1_runs: int = Field(description="Runs on one-label datasets.")


class StudySummary(DojoModel):
    id: str
    suite_id: str
    name: str
    strategy: str
    runs: dict[str, int] = Field(description="The study's runs by status.")
    complete: bool = Field(
        description="Every dataset of the suite has a finished run with "
        "metrics. Only complete studies are ranked."
    )
    totals: StudyTotals
    metrics_pending: int = Field(
        description="Finished runs whose metrics are not calculated yet. Reading "
        "the study calculates them; the totals leave them out until then."
    )
    created_by: int | None
    created_by_agent: str | None = None
    created_at: datetime


class SuiteView(SuiteSummary):
    items: list[SuiteDataset] = Field(max_length=MAX_SUITE_DATASETS)
    leaderboard: list[StudySummary] = Field(
        max_length=MAX_SUITE_STUDIES,
        description="Complete studies, best first: by mean VUS-PR, then "
        "PR-AUC, then detection rate.",
    )
    unfinished: list[StudySummary] = Field(
        max_length=MAX_SUITE_STUDIES,
        description="Studies still running, or with a failed run or metrics "
        "still to calculate, newest first.",
    )


class StudyCreate(DojoModel):
    """Replay one design over every dataset of a suite, one run each."""

    suite_id: str
    name: str = Field(default="", max_length=120)
    definition: PipelineDefinition = Field(
        description="The design, as the pipeline library stores a draft."
    )
    bindings: dict[str, str] = Field(
        default_factory=dict,
        max_length=MAX_DATASET_SERIES,
        description="Input slot ids of the design mapped to a series name, "
        "looked up in each dataset. A slot left out takes the series named "
        "like its id or label, or a dataset's only series when the design "
        "has one input.",
    )
    alignment: RunAlignment = Field(default_factory=RunAlignment)


class StudyListQuery(DojoModel):
    suite_id: str | None = None
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    mine: bool = Field(
        default=False,
        description="Only what the caller made: a key's own, or the member's own.",
    )


class StudyListPage(DojoModel):
    items: list[StudySummary] = Field(max_length=100)
    next_offset: int | None = None


class StudyItem(DojoModel):
    """One dataset of the study: its run and, once calculated, its metrics."""

    dataset_id: str
    dataset_name: str
    run_id: str
    status: RunStatus
    error: str | None
    metrics: RunMetrics | None = Field(
        default=None,
        description="Null until the run has finished and its metrics are calculated.",
    )


class ProtocolLevel(DojoModel):
    """The faults of one family at one size."""

    level: float | None = Field(
        description="The size in short-term noise, the noise factor, or null "
        "for a family without sizes."
    )
    faults: int
    scored: int = Field(
        description="Faults the design scored, leaving out confounded ones."
    )
    caught: int
    confounded: int = Field(
        description="Faults over a span where the clean copy alarmed too: "
        "something in the history, not the fault, may have caused the alarm."
    )
    rate: float | None
    low: float | None = Field(description="Lower end of the 95% Wilson interval.")
    high: float | None = Field(description="Upper end of the 95% Wilson interval.")
    simple_rules: int = Field(description="Faults the simple rules catch.")


class ProtocolFamily(DojoModel):
    """How a design does on one family of planted faults."""

    family: str
    title: str
    measure: Literal["sigmas", "factor", "values", "none"]
    sanity: bool = Field(
        description="Impossible values every design should catch; a miss is "
        "a bug in the design."
    )
    faults: int
    scored: int
    caught: int
    chance_detections: float | None
    adjusted_detection_rate: float | None = Field(
        description="Catches beyond chance at the clean copy's alarm share: 0 "
        "for chance or an alarm that never stops, 1 for every fault."
    )
    half: float | None = Field(
        description="The size at which half the faults are caught, from a "
        "monotone fit along log size; null if never."
    )
    ninety: float | None = Field(
        description="The size at which nine in ten are caught; null if never."
    )
    median_delay_seconds: float | None
    median_sigmas_at_detection: float | None = Field(
        description="For faults that grow: how big they had grown, in "
        "short-term noise, when first caught."
    )
    simple_rules_caught: int
    levels: list[ProtocolLevel]


class ProtocolReport(DojoModel):
    """A study on a protocol suite: the false-alarm budget on the clean copy,
    then a detection profile per fault family, catches counted only where the
    clean copy stayed quiet."""

    protocol: str
    version: int
    purpose: Literal["practice", "test"]
    seed: int | None = Field(
        description="Hidden from keys on a test suite until a member reviews it."
    )
    warmup_values: int | None
    window_values: int | None
    clean_run_id: str | None
    false_alarms_per_day: float | None = Field(
        description="Alarm onsets per day on the clean copy."
    )
    alarm_share: float | None = Field(
        description="Share of the clean copy's scored results in alarm."
    )
    budget_per_day: float
    budget_share: float
    within_budget: bool | None = Field(
        description="Both clean-copy numbers within the budget; null until "
        "the clean run is scored. Catches of a design over budget say little."
    )
    adjusted_detection_rate: float | None = Field(
        description="Mean of the families' chance-adjusted catch rates, each "
        "family weighted equally, sanity faults left out."
    )
    faults: int
    caught: int
    simple_rules_caught: int = Field(
        description="Faults that trivial rules catch: a value 4σ from the "
        "recent median, 10 identical values, or a long silence."
    )
    sanity_missed: int
    untestable: list[str] = Field(
        description="Grid cells that did not fit the history, by cell id."
    )
    families: list[ProtocolFamily]
    headline: str = Field(description="One sentence for a proposal.")


class StudyView(StudySummary):
    definition: dict[str, Any] = Field(description="The compiled design.")
    bindings: dict[str, str] = Field(
        description="Input slot ids mapped to the series name each run used."
    )
    alignment: RunAlignment
    items: list[StudyItem] = Field(max_length=MAX_SUITE_DATASETS)
    protocol: ProtocolReport | None = Field(
        default=None,
        description="On a protocol suite: the detection profile, once the "
        "clean run and the faulted runs are scored.",
    )


StudyMetric = Literal["vus_pr", "pr_auc", "auroc", "detection_rate"]


class StudyComparisonQuery(DojoModel):
    baseline: str = Field(description="The study to compare against.")
    challenger: str
    metric: StudyMetric = "vus_pr"


class PairedDataset(DojoModel):
    dataset_id: str
    dataset_name: str
    baseline: float | None
    challenger: float | None
    delta: float | None = Field(description="challenger - baseline.")


class StudyComparison(DojoModel):
    """Two studies of one suite, dataset by dataset.

    The Wilcoxon signed-rank test asks whether the challenger's gains across
    datasets could be chance (Demšar 2006). Datasets where either study has
    no value are left out; ties count for neither.
    """

    suite_id: str
    metric: StudyMetric
    baseline: str
    challenger: str
    datasets: list[PairedDataset] = Field(max_length=MAX_SUITE_DATASETS)
    compared: int = Field(description="Datasets where both have a value.")
    wins: int
    losses: int
    ties: int
    mean_delta: float | None
    median_delta: float | None
    p_value: float | None = Field(
        description="Two-sided Wilcoxon signed-rank p-value; exact without "
        "tied differences, else the normal approximation. Null with fewer "
        "than two differences that are not zero."
    )
