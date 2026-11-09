"""Alarms by catalogue device and reading.

Alarms are stored under recorded identities, while people and agents choose
devices and readings from the catalogue. These requests and answers carry
catalogue ids and names only, so a caller never needs the recorded identity
behind them.
"""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

# How storage marks an alarm a monitor raised over several readings together.
MULTIVARIATE_TELEMETRY_TYPE = "__multivariate__"
PROBABILITY_VALUE_TYPES = ("tail_pvalue", "conformal_pvalue")
MAX_ALARM_READINGS = 200


def resolve_alarm_value_type(alarm_type: str, value_type: str | None) -> str:
    if value_type is not None:
        return value_type
    if alarm_type.lower().startswith("ml_tailprob_"):
        return "tail_pvalue"
    if alarm_type.lower().startswith("ml_conformal_static_"):
        return "conformal_pvalue"
    return "zscore"


class Alarm(BaseModel):
    alarm_id: str
    timestamp: datetime
    device_id: str | None = Field(
        description="Catalogue device of its readings; null for readings without "
        "a device, or when the catalogue no longer has them."
    )
    device_label: str | None = Field(
        description="Catalogue name of that device, or of the broker for readings "
        "without a device; null when the catalogue no longer has them."
    )
    reading_ids: list[str] = Field(
        description="Catalogue readings the alarm is about. Readings the "
        "catalogue no longer has are left out."
    )
    reading_labels: dict[str, str] = Field(
        description="Catalogue name of each of `reading_ids`."
    )
    multivariate: bool = Field(
        description="Raised by a monitor over several readings together. An "
        "empty `reading_ids` then means the monitor did not record which ones."
    )
    alarm_type: str
    value: float
    value_type: str | None = Field(
        default=None,
        description="`tail_pvalue` or `conformal_pvalue` when `value` is a "
        "p-value; other values are detector scores.",
    )
    monitor_id: str | None = Field(
        default=None, description="Monitor that raised it; null for manual alarms."
    )


class AlarmCursor(BaseModel):
    """Position after the last alarm of a page, newest first."""

    timestamp: datetime
    alarm_id: str


class AlarmQuery(BaseModel):
    reading_ids: list[str] | None = Field(
        default=None,
        max_length=20000,
        description="Catalogue reading ids from `GET /v1/catalogue`. Omit for "
        "every alarm. An alarm is in scope when one of its readings is; a "
        "multivariate alarm without recorded readings only when every reading "
        "of its device is.",
    )
    reading_id: str | None = Field(
        default=None,
        min_length=1,
        description="Narrow to one reading, for example one of the `readings` "
        "of an earlier answer.",
    )
    monitor_id: str | None = Field(
        default=None, min_length=1, description="Only alarms of this monitor."
    )
    since: datetime | None = Field(default=None, description="At or after this time.")
    until: datetime | None = Field(default=None, description="Before this time.")
    max_p_value: float | None = Field(
        default=None,
        gt=0,
        le=1,
        description="Only p-value results at or below this; detector scores "
        "without a p-value are left out.",
    )
    limit: int = Field(default=200, ge=1, le=1000)
    before: AlarmCursor | None = Field(
        default=None, description="`next` of the previous page."
    )


class AlarmSummary(BaseModel):
    count: int = Field(description="Alarms matching the query, on all pages.")
    devices: int = Field(
        description="Devices among them, counting a broker once for its readings "
        "without a device."
    )
    latest: datetime | None = Field(description="Newest matching alarm.")


class AlarmReadingCount(BaseModel):
    reading_id: str
    device_id: str | None
    device_label: str | None
    label: str
    count: int


class AlarmPage(BaseModel):
    items: list[Alarm] = Field(description="Newest first.")
    next: AlarmCursor | None = Field(
        description="Pass as `before` for older alarms; null on the last page."
    )
    summary: AlarmSummary
    readings: list[AlarmReadingCount] = Field(
        description="Readings with alarms in the `reading_ids` scope, before the "
        "reading, time, monitor and p-value filters, so a caller can offer them "
        "as choices."
    )
    unknown_reading_ids: list[str] = Field(
        default_factory=list,
        description="Requested reading ids the catalogue does not have; ignored.",
    )


class AlarmCreate(BaseModel):
    """An alarm an external detector raised."""

    reading_ids: list[str] = Field(
        min_length=1,
        max_length=MAX_ALARM_READINGS,
        description="Catalogue readings it is about, all of one device or, "
        "without a device, of one broker. Several make a multivariate alarm.",
    )
    timestamp: datetime
    alarm_type: str = Field(min_length=1, max_length=200)
    value: float = Field(allow_inf_nan=False)
    value_type: str | None = Field(
        default=None,
        description="How to read `value`; derived from `alarm_type` when omitted.",
    )

    @model_validator(mode="after")
    def validate_probability(self) -> "AlarmCreate":
        if (
            resolve_alarm_value_type(self.alarm_type, self.value_type)
            in PROBABILITY_VALUE_TYPES
            and not 0 <= self.value <= 1
        ):
            raise ValueError("An alarm p-value must be between 0 and 1")
        return self


class AlarmCount(BaseModel):
    count: int
