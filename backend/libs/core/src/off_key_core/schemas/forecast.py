"""Contract of the shared forecast service, used by its callers and by the service.

The service holds pretrained forecasting models (foundation models such as
Timestral, and a seasonal-naive baseline that needs no weights). RADAR workers
and the Dojo send recent readings and get quantile forecasts back, so no model
or weights ever live inside a RADAR container.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Bounds shared by the service and its clients. Timestral reads up to 32,768
# steps of context and forecasts up to 1,024 steps in one pass.
MAX_CONTEXT_LENGTH = 32_768
MAX_HORIZON = 1_024
MAX_BATCH_SIZE = 64
MAX_REQUEST_VALUES = 1_000_000

# The 21 quantile levels Timestral answers on; other providers answer on the same grid.
QUANTILE_LEVELS: tuple[float, ...] = (
    0.01,
    *(round(0.05 * step, 2) for step in range(1, 20)),
    0.99,
)

ModelStatus = Literal["not_downloaded", "downloading", "ready", "failed"]


class ForecastModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ForecastModelInfo(ForecastModel):
    """A model the service offers, and whether it can answer now."""

    id: str
    family: str
    label: str
    parameters: int | None = Field(
        default=None, description="Parameter count, if the model has weights."
    )
    download_bytes: int = Field(
        ge=0, description="Size of the weights to download; 0 for none."
    )
    licence: str
    source: str | None = Field(
        default=None, description="Where the weights come from, such as a Hub repo."
    )
    revision: str | None = None
    levels: tuple[float, ...]
    max_context: int
    max_horizon: int
    status: ModelStatus
    progress: float | None = Field(
        default=None, ge=0, le=1, description="Download progress while downloading."
    )
    error: str | None = None


class ForecastModelList(ForecastModel):
    models: list[ForecastModelInfo]


class ForecastRequest(ForecastModel):
    """Forecast ``horizon`` steps after each series in one batch.

    Missing readings are ``null``; every series ends at the latest reading.
    """

    model: str = Field(min_length=1, max_length=200)
    series: list[list[float | None]] = Field(min_length=1, max_length=MAX_BATCH_SIZE)
    horizon: int = Field(ge=1, le=MAX_HORIZON)

    @model_validator(mode="after")
    def bounded(self) -> "ForecastRequest":
        for values in self.series:
            if not values:
                raise ValueError("Every series needs at least one reading")
            if len(values) > MAX_CONTEXT_LENGTH:
                raise ValueError(
                    f"A series may hold at most {MAX_CONTEXT_LENGTH} readings"
                )
            if all(value is None for value in values):
                raise ValueError("Every series needs at least one reading")
        if sum(len(values) for values in self.series) > MAX_REQUEST_VALUES:
            raise ValueError(
                f"A request may hold at most {MAX_REQUEST_VALUES} readings"
            )
        return self


class ForecastResponse(ForecastModel):
    """``quantiles[series][step][level]``, non-decreasing along the levels."""

    model: str
    revision: str | None
    levels: tuple[float, ...]
    quantiles: list[list[list[float]]]
    elapsed_ms: float = Field(ge=0)


class ForecastUnavailable(ForecastModel):
    """Why a model cannot answer yet; downloads start on first use."""

    model: str
    status: ModelStatus
    progress: float | None = None
    error: str | None = None
    retry_after_seconds: int | None = None
