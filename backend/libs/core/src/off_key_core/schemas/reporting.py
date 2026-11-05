"""Reporting asks for alarms by catalogue reading, time and strength.

Alarms are stored by recorded identity (`charger_id`, `telemetry_type`,
`sensor_set`), while people and agents choose readings from the catalogue. The
query takes catalogue reading ids, and the answer carries catalogue labels, so
a caller never has to join the two itself.
"""

from datetime import datetime

from pydantic import BaseModel, Field

MULTIVARIATE_TELEMETRY_TYPE = "__multivariate__"
PROBABILITY_VALUE_TYPES = ("tail_pvalue", "conformal_pvalue")


class AnomalyCursor(BaseModel):
    """Position after the last alarm of a page, newest first."""

    timestamp: datetime
    anomaly_id: str


class RecordedReading(BaseModel):
    charger_id: str = Field(description="Recorded entity, `entity_id` of a binding.")
    telemetry_key: str = Field(description="Recorded reading key of that entity.")


class AnomalyQuery(BaseModel):
    stream_ids: list[str] | None = Field(
        default=None,
        max_length=20000,
        description="Catalogue reading ids from `GET /v1/system`. Omit for every "
        "entity. An alarm is in scope when one of its readings is; a "
        "multivariate alarm without a sensor set only when every reading of its "
        "entity is.",
    )
    reading: RecordedReading | None = Field(
        default=None,
        description="Narrow to one recorded reading, for example one of the "
        "`readings` of an earlier answer.",
    )
    service_id: str | None = Field(
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
    before: AnomalyCursor | None = Field(
        default=None, description="`next` of the previous page."
    )


class ReadingLabel(BaseModel):
    key: str
    label: str


class ReportedAnomaly(BaseModel):
    anomaly_id: str
    charger_id: str
    timestamp: datetime
    telemetry_type: str = Field(
        description=f"Reading key, or `{MULTIVARIATE_TELEMETRY_TYPE}` for a "
        "monitor over several readings."
    )
    anomaly_type: str
    anomaly_value: float
    value_type: str | None = Field(
        default=None,
        description="`tail_pvalue` or `conformal_pvalue` for p-values; other "
        "values are detector scores.",
    )
    sensor_set: list[str] | None = None
    service_id: str | None = Field(
        default=None, description="Monitor that raised it; empty for manual alarms."
    )
    entity_label: str = Field(description="Catalogue name of the entity.")
    telemetry_label: str | None = Field(
        default=None,
        description="Catalogue name of `telemetry_type`; null for multivariate.",
    )
    readings: list[ReadingLabel] = Field(
        description="The readings this alarm is about, with catalogue names."
    )


class AnomalySummary(BaseModel):
    count: int = Field(description="Alarms matching the query, on all pages.")
    entities: int = Field(description="Entities among them.")
    latest: datetime | None = Field(description="Newest matching alarm.")


class ReadingCount(BaseModel):
    charger_id: str
    telemetry_key: str
    entity_label: str
    label: str
    count: int


class AnomalyPage(BaseModel):
    items: list[ReportedAnomaly] = Field(description="Newest first.")
    next: AnomalyCursor | None = Field(
        description="Pass as `before` for older alarms; null on the last page."
    )
    summary: AnomalySummary
    readings: list[ReadingCount] = Field(
        description="Readings with alarms in the `stream_ids` scope, before the "
        "reading, time, monitor and p-value filters, so a caller can offer them "
        "as choices."
    )
    unknown_stream_ids: list[str] = Field(
        default_factory=list,
        description="Requested reading ids the catalogue does not have; ignored.",
    )
