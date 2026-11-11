"""What a deployed worker sees of the forecast service, as one JSON line.

The deployment test pipes this file into a worker container, so it reaches the
service the way a worker does: by the address in its environment and the token
Swarm mounted as a secret. It needs only what the RADAR image carries.
"""

import json
import math
import os
import sys
import time
from pathlib import Path

from off_key_mqtt_radar.forecasting import (
    ForecastClient,
    ForecastClientSettings,
    ForecastServiceError,
    service_client,
)

SEASON = 24
CONTEXT = 512
HORIZON = 24
# A checkpoint's first download and the first forecast that loads its weights.
DOWNLOAD_SECONDS = 300
FIRST_FORECAST_SECONDS = 120


def seasonal(index: int) -> float:
    """A clean daily shape: one large wave and one harmonic."""
    turn = 2 * math.pi * index / SEASON
    return 10 + 3 * math.sin(turn) + 0.5 * math.sin(2 * turn)


def refused_without_token(url: str) -> bool:
    try:
        ForecastClient(url).models()
    except ForecastServiceError as error:
        return error.status == 401
    return False


def wait_until_ready(client: ForecastClient, model: str) -> dict:
    """Ask for the weights and wait; a failed download is asked for again."""
    deadline = time.monotonic() + DOWNLOAD_SECONDS
    downloads = 0
    while True:
        info = client.model(model)
        if info is None:
            return {"status": "not_offered", "downloads": downloads}
        if info.status == "ready" or time.monotonic() > deadline:
            return {
                "status": info.status,
                "error": info.error,
                "downloads": downloads,
                "revision": info.revision,
            }
        if info.status in {"not_downloaded", "failed"}:
            client.request_download(model)
            downloads += 1
        time.sleep(3)


def main(model: str) -> dict:
    settings = ForecastClientSettings()
    secret = Path("/run/secrets/FORECAST_API_TOKEN")
    report: dict = {
        "url": settings.FORECAST_API_URL,
        "token_is_a_mounted_secret": secret.is_file(),
        "token_in_environment": "FORECAST_API_TOKEN" in os.environ,
        "refused_without_token": refused_without_token(settings.FORECAST_API_URL),
    }
    # The client every forecaster step of this worker would use.
    report["offered"] = {
        item.id: item.revision
        for item in service_client().models()
        if item.family == "timestral"
    }
    token = settings.FORECAST_API_TOKEN
    patient = ForecastClient(
        settings.FORECAST_API_URL,
        token=token.get_secret_value() if token else None,
        timeout=FIRST_FORECAST_SECONDS,
    )
    report["model"] = wait_until_ready(patient, model)
    if report["model"]["status"] != "ready":
        return report
    answer = patient.forecast(
        model, [[seasonal(index) for index in range(CONTEXT)]], HORIZON
    )
    truth = [seasonal(index) for index in range(CONTEXT, CONTEXT + HORIZON)]
    steps = answer.quantiles[0]
    median = answer.levels.index(0.5)
    low, high = answer.levels.index(0.05), answer.levels.index(0.95)
    report["forecast"] = {
        "revision": answer.revision,
        "levels": list(answer.levels),
        "mean_absolute_error": sum(
            abs(step[median] - value) for step, value in zip(steps, truth, strict=True)
        )
        / HORIZON,
        "covered": sum(
            step[low] <= value <= step[high]
            for step, value in zip(steps, truth, strict=True)
        ),
        "steps": len(steps),
    }
    return report


if __name__ == "__main__":
    print(json.dumps(main(sys.argv[1])))
