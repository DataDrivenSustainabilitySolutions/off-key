"""A small client of the shared forecast service's HTTP API.

RADAR workers and the Dojo ask the service for forecasts; TACTIC asks which
models it holds and starts their downloads. All of them are named the service
and its token by their deployment.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from ..config.validation import SECRETS_DIR
from ..schemas.forecast import ForecastModelInfo, ForecastModelList, ForecastResponse

# (method, url, body, headers) -> (status, body)
Transport = Callable[[str, str, bytes | None, dict[str, str]], tuple[int, bytes]]


class ForecastServiceError(RuntimeError):
    """The forecast service gave no answer, or refused the request."""

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
    """Where a process reaches the forecast service, from its environment."""

    FORECAST_API_URL: str = ""
    FORECAST_API_TOKEN: SecretStr | None = None
    FORECAST_API_TIMEOUT: float = Field(default=10.0, gt=0, le=120)

    model_config = SettingsConfigDict(
        case_sensitive=True, extra="ignore", secrets_dir=SECRETS_DIR
    )


def service_client(
    url: str | None = None, *, timeout: float | None = None
) -> ForecastClient:
    """The forecast service this process is deployed beside.

    A caller that is told the address another way (TACTIC) passes ``url``; the
    token and the timeout still come from its environment.
    """
    settings = ForecastClientSettings()
    token = settings.FORECAST_API_TOKEN
    return ForecastClient(
        settings.FORECAST_API_URL if url is None else url,
        token=token.get_secret_value() if token else None,
        timeout=settings.FORECAST_API_TIMEOUT if timeout is None else timeout,
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
