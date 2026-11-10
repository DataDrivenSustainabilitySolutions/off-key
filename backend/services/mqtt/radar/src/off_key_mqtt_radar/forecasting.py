"""Pretrained forecasters behind the shared forecast service.

The weights live in the forecast service, never in a RADAR worker. A worker
keeps the recent values of one feature, sends them to the service and gets
quantile forecasts back. ``ServiceForecaster`` gives that exchange Aberrant's
forecaster interface, so Aberrant's residual detector, nonconformity scores and
calibrators treat a pretrained model like any online forecaster.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import time
import urllib.error
import urllib.request
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from aberrant.base import ConfigurationError, ConfigurationIssue
from aberrant.base.forecast import Forecast
from aberrant.base.protocols import FeatureMap
from aberrant.catalog import (
    ComponentConfig,
    DetectorConfig,
    EventKind,
    FeatureCount,
    FeatureSchemaKind,
    ModelCapabilities,
    ScoreKind,
    StateKind,
    WarmupRequirement,
    WarmupUnit,
)
from aberrant.forecast import ResidualDetector
from off_key_core.config.validation import SECRETS_DIR
from off_key_core.schemas.forecast import (
    MAX_CONTEXT_LENGTH,
    MAX_HORIZON,
    ForecastModelInfo,
    ForecastModelList,
    ForecastResponse,
)
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from .execution_errors import FatalExecutionError, ObservationRejected

logger = logging.getLogger(__name__)

# The interquartile range of a normal distribution spans this many deviations.
_IQR_DEVIATIONS = 1.349
# A failing service is logged at most this often per forecaster.
_FAILURE_LOG_SECONDS = 60.0
# A service that could not be asked to have a model ready is asked again after this.
_PREPARE_SECONDS = 30.0
# A service that took this long to fail is not asked again for a while, so a
# worker does not wait out a timeout for every value while the service hangs.
_SLOW_FAILURE_SECONDS = 2.0
_PAUSE_SECONDS = 15.0

# (method, url, body, headers) -> (status, body)
Transport = Callable[[str, str, bytes | None, dict[str, str]], tuple[int, bytes]]


class ForecastServiceError(RuntimeError):
    """The forecast service gave no forecast."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def _urllib_transport(timeout: float) -> Transport:
    def send(
        method: str, url: str, body: bytes | None, headers: dict[str, str]
    ) -> tuple[int, bytes]:
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ForecastServiceError(
                f"Forecast service is unreachable: {error}"
            ) from error

    return send


class ForecastClient:
    """A small synchronous client of the forecast service's HTTP API."""

    def __init__(
        self,
        base_url: str,
        *,
        token: str | None = None,
        timeout: float = 10.0,
        transport: Transport | None = None,
    ):
        if not base_url:
            raise ValueError("The forecast service URL is not configured")
        self.base_url = base_url.rstrip("/")
        self._headers = {"Content-Type": "application/json"}
        if token:
            self._headers["Authorization"] = f"Bearer {token}"
        self._send = transport or _urllib_transport(timeout)

    def _call(self, method: str, path: str, payload: dict | None = None) -> Any:
        body = None if payload is None else json.dumps(payload).encode()
        status, content = self._send(
            method, f"{self.base_url}{path}", body, dict(self._headers)
        )
        try:
            data = json.loads(content) if content else None
        except ValueError:
            data = None
        if status >= 400:
            raise ForecastServiceError(_reason(status, data), status=status)
        return data

    def models(self) -> list[ForecastModelInfo]:
        return ForecastModelList.model_validate(self._call("GET", "/v1/models")).models

    def model(self, model_id: str) -> ForecastModelInfo | None:
        return next((item for item in self.models() if item.id == model_id), None)

    def request_download(self, model_id: str) -> ForecastModelInfo:
        """Start downloading a model's weights; returns at once."""
        return ForecastModelInfo.model_validate(
            self._call("POST", "/v1/downloads", {"model": model_id})
        )

    def forecast(
        self, model_id: str, series: Sequence[Sequence[float | None]], horizon: int
    ) -> ForecastResponse:
        return ForecastResponse.model_validate(
            self._call(
                "POST",
                "/v1/forecast",
                {
                    "model": model_id,
                    "series": [list(values) for values in series],
                    "horizon": horizon,
                },
            )
        )


class ForecastClientSettings(BaseSettings):
    """Where a worker reaches the forecast service, from its environment."""

    FORECAST_API_URL: str = ""
    FORECAST_API_TOKEN: SecretStr | None = None
    FORECAST_API_TIMEOUT: float = Field(default=10.0, gt=0, le=120)

    model_config = SettingsConfigDict(
        case_sensitive=True, extra="ignore", secrets_dir=SECRETS_DIR
    )


def service_client() -> ForecastClient:
    """The forecast service this worker is deployed beside."""
    settings = ForecastClientSettings()
    token = settings.FORECAST_API_TOKEN
    return ForecastClient(
        settings.FORECAST_API_URL,
        token=token.get_secret_value() if token else None,
        timeout=settings.FORECAST_API_TIMEOUT,
    )


def _reason(status: int, data: Any) -> str:
    if isinstance(data, dict):
        if data.get("status") == "downloading":
            return "The forecast model is still downloading"
        if data.get("status") in {"not_downloaded", "failed"}:
            detail = data.get("error") or data["status"]
            return f"The forecast model is not ready: {detail}"
        if isinstance(data.get("detail"), str):
            return f"Forecast service refused the request: {data['detail']}"
    return f"Forecast service answered {status}"


def forecast_from_quantiles(
    origin: int,
    levels: Sequence[float],
    quantiles: Sequence[Sequence[float]],
    min_scale: float,
) -> Forecast:
    """Aberrant's forecast for leads ``1..horizon`` from one series' quantiles.

    The point forecast is the median. The spread is the interquartile range in
    normal deviations, so a scaled residual reads like a z-score.
    """
    forecast = Forecast(
        origin=origin,
        leads=tuple(range(1, len(quantiles) + 1)),
        mean=tuple(0.0 for _ in quantiles),
        levels=tuple(levels),
        quantiles=tuple(tuple(row) for row in quantiles),
    )
    leads = forecast.leads
    return Forecast(
        origin=origin,
        leads=leads,
        mean=tuple(forecast.quantile(lead, 0.5) for lead in leads),
        scale=tuple(
            max(
                min_scale,
                (forecast.quantile(lead, 0.75) - forecast.quantile(lead, 0.25))
                / _IQR_DEVIATIONS,
            )
            for lead in leads
        ),
        levels=forecast.levels,
        quantiles=forecast.quantiles,
    )


class ServiceForecaster:
    """A pretrained model in the forecast service, as an Aberrant forecaster.

    ``learn_one(y)`` keeps the latest ``context_length`` values and learns
    nothing else: the model's weights are frozen. ``forecast_one()`` asks the
    service to forecast leads ``1..horizon`` from those values, once at least
    ``minimum_context`` have arrived.

    A request the service cannot answer gives no forecast: ``forecast_one()``
    returns ``None`` and ``last_error`` says why. The values are kept either
    way, so forecasts resume when the service does. Because the weights never
    change, a missed forecast can be made later from the same values:
    ``forecast_from(back)`` forecasts as of ``back`` values ago.

    The first value asks the service to have the model ready, so weights it
    has to download are usually there before the first forecast is due. A
    service that does not offer the model ends the run: no later value could
    be scored either.

    ``client`` makes the connection on first use; without one the worker's
    environment says where the service is. It is stored in checkpoints by
    reference, so it must be a module-level function.
    """

    def __init__(
        self,
        model: str,
        *,
        horizon: int = 1,
        context_length: int = 512,
        minimum_context: int = 32,
        min_scale: float = 1e-6,
        client: Callable[[], ForecastClient] | None = None,
    ):
        if not isinstance(model, str) or not model:
            raise ValueError("model must name a forecast model")
        if not 1 <= horizon <= MAX_HORIZON:
            raise ValueError(f"horizon must be from 1 to {MAX_HORIZON}")
        if not 1 <= context_length <= MAX_CONTEXT_LENGTH:
            raise ValueError(f"context_length must be from 1 to {MAX_CONTEXT_LENGTH}")
        if not 1 <= minimum_context <= context_length:
            raise ValueError("minimum_context must be from 1 to context_length")
        if not min_scale > 0:
            raise ValueError("min_scale must be positive")
        self.model = model
        self._horizon = horizon
        self.context_length = context_length
        self.minimum_context = minimum_context
        self.min_scale = min_scale
        self._client_factory = client
        self._client: ForecastClient | None = None
        self.reset()

    @property
    def horizon(self) -> int:
        return self._horizon

    @property
    def is_ready(self) -> bool:
        return self.n_samples_seen >= self.minimum_context

    def reset(self) -> None:
        self.n_samples_seen = 0
        # Enough values to repeat any forecast a residual detector still holds.
        self._values: deque[float] = deque(
            maxlen=self.context_length + self._horizon - 1
        )
        self.failures = 0
        self.last_error: str | None = None
        self._logged_at = 0.0
        # When the service is next asked to have the model ready, and until
        # when it is left alone after a slow failure; both on the monotonic clock.
        self._prepare_at = 0.0
        self._paused_until = 0.0

    def learn_one(self, y: float) -> None:
        self._values.append(float(y))
        self.n_samples_seen += 1
        if time.monotonic() >= self._prepare_at:
            self.prepare()

    def prepare(self) -> ForecastModelInfo | None:
        """Ask the service to have the model ready, downloading it if needed.

        Returns the model as the service describes it, or ``None`` when the
        service could not be asked; it is then asked again later.

        Raises:
            FatalExecutionError: The service does not offer the model.
        """
        try:
            info = self._ask(lambda client: client.request_download(self.model))
        except ForecastServiceError:
            self._prepare_at = time.monotonic() + _PREPARE_SECONDS
            return None
        self._prepare_at = math.inf
        return info

    def _ask(self, request: Callable[[ForecastClient], Any]) -> Any:
        """One request to the service, with its failure counted and explained."""
        started = time.monotonic()
        try:
            if started < self._paused_until:
                raise ForecastServiceError(
                    self.last_error or "Forecast service is not asked again yet"
                )
            if self._client is None:
                self._client = (self._client_factory or service_client)()
            return request(self._client)
        except ForecastServiceError as error:
            now = time.monotonic()
            if now - started >= _SLOW_FAILURE_SECONDS:
                self._paused_until = now + _PAUSE_SECONDS
            self._failed(error)
            if error.status == 404:
                raise FatalExecutionError(
                    f"The forecast service does not offer {self.model}: {error}"
                ) from error
            raise

    def context(self, back: int = 0) -> list[float]:
        """The values the model reads for a forecast made ``back`` values ago."""
        end = len(self._values) - back
        return list(self._values)[max(0, end - self.context_length) : end]

    def forecast_from(self, back: int = 0) -> Forecast | None:
        """The forecast as of ``back`` values ago, or ``None`` before readiness.

        Raises:
            ForecastServiceError: The service gave no usable forecast.
        """
        if not 0 <= back < self._horizon:
            raise ValueError("back must be from 0 to horizon - 1")
        origin = self.n_samples_seen - back
        if origin < self.minimum_context:
            return None
        response = self._ask(
            lambda client: client.forecast(
                self.model, [self.context(back)], self._horizon
            )
        )
        try:
            forecast = forecast_from_quantiles(
                origin, response.levels, response.quantiles[0], self.min_scale
            )
        except (ValueError, IndexError) as error:
            self._failed(error)
            raise ForecastServiceError(
                f"Forecast service gave an unusable forecast: {error}"
            ) from error
        self.last_error = None
        return forecast

    def forecast_one(self) -> Forecast | None:
        try:
            return self.forecast_from()
        except ForecastServiceError:
            return None

    def _failed(self, error: Exception) -> None:
        self.failures += 1
        self.last_error = str(error)
        now = time.monotonic()
        if now - self._logged_at >= _FAILURE_LOG_SECONDS:
            self._logged_at = now
            logger.warning(
                "Forecast service did not answer for %s (%d so far): %s",
                self.model,
                self.failures,
                error,
            )

    def __getstate__(self) -> dict[str, Any]:
        # A checkpoint keeps the values, not the connection or this worker's clock.
        state = self.__dict__.copy()
        state["_client"] = None
        state["_logged_at"] = state["_prepare_at"] = state["_paused_until"] = 0.0
        return state

    def __repr__(self) -> str:
        return (
            f"ServiceForecaster({self.model!r}, horizon={self._horizon}, "
            f"context_length={self.context_length})"
        )


class ServiceResidualDetector(ResidualDetector):
    """Scores a feature against a pretrained model's forecast.

    Aberrant's residual detector scores 0 when it holds no forecast. That is
    right before the forecaster is ready, but not when the service failed to
    answer: the missed forecast is asked for again, and an observation that
    still has none is rejected, which counts as lost coverage, not as normal.
    """

    def __init__(
        self,
        model: ServiceForecaster,
        target: str,
        *,
        lead: int = 1,
        score: str = "scaled",
    ):
        if not isinstance(model, ServiceForecaster):
            raise TypeError("model must be a forecaster in the forecast service")
        super().__init__(model, target, lead=lead, score=score)  # type: ignore[arg-type]

    def explain_one(self, x: FeatureMap) -> tuple[float, float | None, float | None]:
        issued = self._issued
        if len(issued) == self.lead and issued[0] is None:
            # The forecast for this observation was made `lead` values ago.
            try:
                issued[0] = self.model.forecast_from(self.lead - 1)
            except ForecastServiceError as error:
                raise ObservationRejected(
                    f"No forecast to compare with: {error}"
                ) from error
        return super().explain_one(x)


@dataclass(frozen=True)
class ResolvedServiceDetector:
    """What RADAR reads of a resolved detector, for a pretrained forecaster.

    Aberrant resolves its own components from configuration. This one is built
    here, around the forecast service, and answers the same questions.
    """

    config: DetectorConfig
    capabilities: ModelCapabilities
    fingerprint: str

    def build(self) -> ServiceResidualDetector:
        params = self.config.model.params
        forecaster = dict(params["model"]["params"])
        return ServiceResidualDetector(
            ServiceForecaster(forecaster.pop("checkpoint"), **forecaster),
            params["target"],
            lead=params["lead"],
            score=params["score"],
        )


def resolve_service_detector(model: Mapping[str, Any]) -> ResolvedServiceDetector:
    """Resolve a pretrained forecaster step, given as Aberrant's residual detector
    around a forecaster of the forecast service."""
    config = DetectorConfig(model=ComponentConfig(model["id"], model["params"]))
    params = config.model.params
    capabilities = ModelCapabilities(
        event_kind=EventKind.UNIVARIATE,
        feature_count=FeatureCount(1, 1),
        feature_schema=FeatureSchemaKind.FIXED,
        score_kind=ScoreKind.NON_NEGATIVE,
        higher_is_more_anomalous=True,
        warmup=WarmupRequirement(
            params["model"]["params"]["minimum_context"] + params["lead"] - 1,
            WarmupUnit.EVENTS,
        ),
        state=StateKind.BOUNDED,
        resettable=False,
        requires_unit_interval=False,
    )
    serialized = json.dumps(config.as_dict(), sort_keys=True, separators=(",", ":"))
    resolved = ResolvedServiceDetector(
        config, capabilities, hashlib.sha256(serialized.encode()).hexdigest()
    )
    # Settings out of range fail here, before a run subscribes or learns.
    resolved.build()
    # So does a worker that cannot name the service: it could score nothing.
    # Naming the service opens no connection.
    try:
        service_client()
    except ValueError as error:
        message = (
            "This deployment has no forecast service, which a pretrained "
            "forecaster needs (FORECAST_API_URL is not set)"
        )
        raise ConfigurationError(
            message, issues=[ConfigurationIssue("forecast_service", (), message)]
        ) from error
    return resolved
