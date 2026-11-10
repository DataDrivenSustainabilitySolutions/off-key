"""HTTP API of the forecast service, reached only on the internal app network."""

from __future__ import annotations

import hmac
import math
import time
from typing import Annotated

import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse
from off_key_core.schemas.forecast import (
    ForecastModelInfo,
    ForecastModelList,
    ForecastRequest,
    ForecastResponse,
    ForecastUnavailable,
)
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from .registry import ModelNotReady, ModelRegistry, UnknownModel

# A caller asks again after this long while weights download.
RETRY_AFTER_SECONDS = 10


class DownloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1, max_length=200)


def create_app(registry: ModelRegistry, api_token: SecretStr | None) -> FastAPI:
    app = FastAPI(
        title="aberration Forecast Service",
        description="Pretrained forecasting models for anomaly detection",
        docs_url=None,
        redoc_url=None,
    )
    guarded = [Depends(_token_guard(api_token))]

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/models", dependencies=guarded)
    def models() -> ForecastModelList:
        return ForecastModelList(models=registry.models())

    @app.post(
        "/v1/downloads",
        dependencies=guarded,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def download(request: DownloadRequest) -> ForecastModelInfo:
        try:
            return registry.request_download(request.model)
        except UnknownModel:
            raise _unknown(request.model) from None

    @app.post(
        "/v1/forecast",
        dependencies=guarded,
        response_model=ForecastResponse,
        responses={503: {"model": ForecastUnavailable}},
    )
    def forecast(request: ForecastRequest) -> ForecastResponse | JSONResponse:
        return _forecast(registry, request)

    return app


def _token_guard(api_token: SecretStr | None):
    def authorized(authorization: Annotated[str | None, Header()] = None) -> None:
        if api_token is None:
            return
        expected = f"Bearer {api_token.get_secret_value()}"
        if authorization is None or not hmac.compare_digest(
            authorization.encode(), expected.encode()
        ):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid service token")

    return authorized


def _forecast(
    registry: ModelRegistry, request: ForecastRequest
) -> ForecastResponse | JSONResponse:
    try:
        info = registry.info(request.model)
        if request.horizon > info.max_horizon:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{info.id} forecasts at most {info.max_horizon} steps",
            )
        model = registry.get(request.model)
    except UnknownModel:
        raise _unknown(request.model) from None
    except ModelNotReady as exc:
        return _unavailable(exc.info)
    # Only the latest readings the model can read are sent on.
    series = [
        np.array(
            [
                math.nan if value is None else value
                for value in values[-info.max_context :]
            ],
            dtype=np.float64,
        )
        for values in request.series
    ]
    started = time.perf_counter()
    quantiles = model.forecast(series, request.horizon)
    elapsed_ms = (time.perf_counter() - started) * 1000
    expected = (len(series), request.horizon, len(info.levels))
    if quantiles.shape != expected or not np.isfinite(quantiles).all():
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"{info.id} returned an invalid forecast",
        )
    return ForecastResponse(
        model=info.id,
        revision=info.revision,
        levels=info.levels,
        quantiles=quantiles.tolist(),
        elapsed_ms=elapsed_ms,
    )


def _unknown(model_id: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown model: {model_id}")


def _unavailable(info: ForecastModelInfo) -> JSONResponse:
    retry = RETRY_AFTER_SECONDS if info.status == "downloading" else None
    body = ForecastUnavailable(
        model=info.id,
        status=info.status,
        progress=info.progress,
        error=info.error,
        retry_after_seconds=retry,
    )
    headers = {"Retry-After": str(retry)} if retry is not None else None
    return JSONResponse(
        body.model_dump(mode="json"),
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        headers=headers,
    )
