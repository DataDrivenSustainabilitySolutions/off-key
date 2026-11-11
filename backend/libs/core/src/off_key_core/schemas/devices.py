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
    truncated: bool = False


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
        "boundary is in the step's own score units, the band around it.",
    )
    threshold: float
    alarm: bool
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
        "boundary is in the step's own score units, the band around it.",
    )
    threshold: float
    alarm: bool
