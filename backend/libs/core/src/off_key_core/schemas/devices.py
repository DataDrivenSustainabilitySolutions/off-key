"""Devices, readings, measurements and detector evidence by catalogue id.

Measurements and evidence are stored under recorded identities, while people and
agents name devices (`devices[].id`) and readings (`readings[].id`) of the
catalogue. These answers carry catalogue ids only, so a caller never needs the
recorded identity behind them.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Device(BaseModel):
    id: str = Field(description="Catalogue device id.")
    label: str
    kind: str
    broker_id: str | None = Field(
        description="Broker the device reports through, when the catalogue sets one."
    )
    parent_id: str | None = Field(description="Device this one belongs to.")
    reading_ids: list[str] = Field(description="Catalogue readings of this device.")
    online: bool = Field(description="Whether the device is currently sending data.")
    last_seen: str | None = Field(description="When data last arrived.")


class Measurement(BaseModel):
    timestamp: str = Field(description="When the value was measured.")
    value: float | None
    created: str = Field(description="When the value arrived; the live cursor.")


class MeasurementCursor(BaseModel):
    created: str
    timestamp: str


class MeasurementPagination(BaseModel):
    limit: int
    has_more: bool
    next_cursor: MeasurementCursor | None


class MeasurementPage(BaseModel):
    data: list[Measurement]
    pagination: MeasurementPagination


class MeasurementBucket(BaseModel):
    timestamp: str
    value: float


class RecentValues(BaseModel):
    """How the newest values of a reading arrive and move."""

    count: int = Field(description="Values looked at, the newest of the window.")
    missing: int = Field(description="Arrivals among them that carried no value.")
    first: datetime
    last: datetime
    interval_seconds: float | None = Field(
        description="The usual time between two values: the median."
    )
    interval_p90_seconds: float | None = Field(
        description=(
            "Nine in ten values arrive within this time of the one before. Far "
            "above the usual interval, the reading reports on change or in bursts."
        )
    )
    gaps: int = Field(description="Pauses longer than five usual intervals.")
    longest_gap_seconds: float | None
    mean: float
    spread: float = Field(description="Standard deviation of the values.")
    median: float
    p05: float = Field(description="One value in twenty lies below this.")
    p95: float = Field(description="One value in twenty lies above this.")
    typical_change: float | None = Field(
        description=(
            "The usual change from one value to the next: the median. Against "
            "the spread it says how noisy the reading is."
        )
    )
    flat_share: float | None = Field(
        description="Share of values that equal the one before, from 0 to 1."
    )
    longest_flat_seconds: float = Field(
        description="The longest time the reading held one value."
    )
    distinct: int = Field(description="How many different values there are.")
    levels: list[float] | None = Field(
        description=(
            "The values themselves where there are at most ten: such a reading "
            "is a state or a counter of few steps, not a measurement."
        )
    )


class SuggestedLag(BaseModel):
    """A lag the partial autocorrelation says carries information of its own."""

    observations: int = Field(description="Steps back on the profile's grid.")
    seconds: float = Field(description="The same lag in time.")
    partial: float = Field(
        description="Partial autocorrelation at this lag, from -1 to 1."
    )


class Season(BaseModel):
    """A repeating cycle: a peak of the autocorrelation."""

    observations: int = Field(description="Steps in one cycle on the profile's grid.")
    seconds: float = Field(description="The same cycle in time.")
    strength: float = Field(description="Autocorrelation at the cycle, from 0 to 1.")


class Autocorrelation(BaseModel):
    """How a series relates to its own past, on an even grid of time.

    Uneven values are put on the grid by taking the last value at or before
    each step, so a lag here is a fixed time back. Correlation is context for
    choosing steps, not a test: it says nothing about which values are wrong.
    """

    step_seconds: float = Field(description="The grid's step, one lag.")
    count: int = Field(description="Values on the grid.")
    regular: bool = Field(
        description=(
            "Whether the values arrived evenly, so the grid holds them as they are."
        )
    )
    acf: list[float] = Field(
        description="Autocorrelation at lags 1, 2 and on, from -1 to 1."
    )
    pacf: list[float] = Field(
        description=(
            "Partial autocorrelation at lags 1, 2 and on: what a lag adds once "
            "the shorter lags are known."
        )
    )
    bound: float = Field(
        description="Values beyond plus or minus this differ from noise (95%)."
    )
    persistent: bool = Field(
        description=(
            "Whether the autocorrelation stays high for many lags: a trend or a "
            "level that wanders, which differencing, decomposing or forecasting "
            "takes out before a detector scores what is left."
        )
    )
    suggested_lags: list[SuggestedLag] = Field(
        default_factory=list,
        description=(
            "Lags worth giving a detector, strongest partial autocorrelation first."
        ),
    )
    seasons: list[Season] = Field(
        default_factory=list,
        description=(
            "Cycles, strongest first. One cycle suits a seasonal forecaster's "
            "season length, a matrix profile's subsequence length and a lag."
        ),
    )


class ReadingProfile(BaseModel):
    """What a reading looks like over a window, so a design can be fitted to it.

    The window is cut into buckets, and what is said about the whole window is
    said from the lowest and highest value of each. ``recent`` looks at the
    newest values one by one.
    """

    reading_id: str = Field(description="Catalogue reading id.")
    start: datetime
    end: datetime
    bucket_seconds: float = Field(description="The time one bucket covers.")
    first: datetime | None = Field(
        default=None, description="The earliest value in the window, if it holds one."
    )
    last: datetime | None = Field(
        default=None,
        description="The latest value in the window, the same moment as recent.last.",
    )
    coverage: float | None = Field(
        default=None,
        description=(
            "Share of the buckets between the first and the last value that "
            "hold a value, from 0 to 1: of the history that exists, not of "
            "the window before it began."
        ),
    )
    longest_outage_seconds: float | None = Field(
        default=None,
        description="The longest run of buckets without a value between them.",
    )
    minimum: float | None = None
    maximum: float | None = None
    daily_rhythm: float | None = Field(
        default=None,
        description=(
            "Share of the reading's variation that the hour of the day explains, "
            "from 0 to 1. Null where the window holds less than two days."
        ),
    )
    weekly_rhythm: float | None = Field(
        default=None,
        description=(
            "Share that the day of the week and the hour together explain. Well "
            "above the daily share, weekdays differ. Null below fourteen days."
        ),
    )
    level_change: float | None = Field(
        default=None,
        description=(
            "How far the level moved from the first day of the window to the "
            "last, in spreads of the reading. Null below two days."
        ),
    )
    recent: RecentValues | None = Field(
        default=None, description="Null where the window holds no value."
    )
    autocorrelation: list[Autocorrelation] = Field(
        default_factory=list,
        description=(
            "How the reading relates to its own past: over its newest values, "
            "then over the whole window in buckets, which shows daily and "
            "weekly cycles. Empty where too few values arrived."
        ),
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Why a figure is null, and where the profile saw less than asked.",
    )


class MeasurementSummary(MeasurementBucket):
    minimum: float
    maximum: float
    count: int
    start: str
    end: str


class MeasurementHistory(BaseModel):
    """Display-only history; raw samples and bucket means are explicit."""

    representation: Literal["raw", "mean"]
    points: list[MeasurementSummary | MeasurementBucket]
    interval_ms: int = 0
    sample_count: int = 0
    extent: tuple[str, str] | None = None
    column_ms: int = Field(
        default=0,
        description=(
            "Raw views only. Above zero, the range held more readings than the "
            "chart can separate: each column of this width, counted from the "
            "epoch, keeps its first, last, lowest and highest reading. Zero "
            "means every reading in the range is returned."
        ),
    )


class ChartEvidence(BaseModel):
    """What a reading chart draws for one observation of a monitor."""

    monitor_id: str
    timestamp: datetime
    sequence_number: int
    reading_ids: list[str] = Field(
        description="Catalogue readings the observation covered."
    )
    input_timestamps: dict[str, datetime] = Field(
        description="Measurement time of each covered reading, by reading id."
    )
    strategy: str
    model_type: str | None = None
    anomaly_score: float | None = None
    restarted_martingale: float | None = None
    tracker_results: list[dict[str, object]] = Field(default_factory=list)
    detector_results: list[dict[str, object]] = Field(default_factory=list)
    detector_inputs: list[dict[str, object]] = Field(default_factory=list)
    forecasts: list[dict[str, object]] = Field(
        default_factory=list,
        description="What each forecaster step expected of the observation: "
        "the step, the feature it scores, the expected value and, when the "
        "boundary is in the step's own score units, the band around it. Optional "
        "issued evidence contains the next real forecast trajectory, its issue "
        "and origin times, model update indices and explicitly estimated target "
        "times. Only the calibrated lead carries a calibrated interval.",
    )
    threshold: float
    alarm: bool
    muted: bool = Field(
        default=False,
        description="The detection rule fired and a Mute alarms step kept the "
        "alarm from being raised; alarm is then false.",
    )
    created: datetime = Field(description="When it was stored; part of the cursor.")


class Evidence(BaseModel):
    """The complete detector evidence of one observation of a monitor."""

    monitor_id: str
    timestamp: datetime
    sequence_number: int
    device_id: str | None = Field(
        description="Catalogue device of the readings; null for readings that "
        "belong to a broker directly."
    )
    reading_ids: list[str]
    input_timestamps: dict[str, datetime]
    strategy: str
    model_type: str | None = None
    p_value: float | None = None
    anomaly_score: float | None = None
    e_value: float | None = None
    e_value_is_infinite: bool
    log_e_value: float | None = None
    restarted_martingale: float | None = None
    restarted_martingale_is_infinite: bool
    log_restarted_martingale: float | None = None
    tracker_results: list[dict[str, object]] = Field(default_factory=list)
    detector_results: list[dict[str, object]] = Field(default_factory=list)
    detector_inputs: list[dict[str, object]] = Field(default_factory=list)
    forecasts: list[dict[str, object]] = Field(
        default_factory=list,
        description="What each forecaster step expected of the observation: "
        "the step, the feature it scores, the expected value and, when the "
        "boundary is in the step's own score units, the band around it. Optional "
        "issued evidence contains the next real forecast trajectory, its issue "
        "and origin times, model update indices and explicitly estimated target "
        "times. Only the calibrated lead carries a calibrated interval.",
    )
    threshold: float
    alarm: bool
    muted: bool = Field(
        default=False,
        description="The detection rule fired and a Mute alarms step kept the "
        "alarm from being raised; alarm is then false.",
    )
