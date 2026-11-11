"""The forecast service's models, as the composer shows them.

The browser never reaches the forecast service. TACTIC asks it, with the token
its deployment mounts, which checkpoints it holds and whether each is
downloaded, and starts a download on a member's behalf.
"""

from off_key_core.config.logs import logger
from off_key_core.schemas.forecast import ForecastModelInfo
from off_key_core.schemas.pipelines import ForecastModelCatalog
from off_key_core.utils.forecast_client import (
    ForecastClient,
    ForecastServiceError,
    service_client,
)

from ...config.config import get_tactic_settings
from ...domain import ConflictError, NotFoundError

# A member waits for this answer, so a service that hangs is given up on early.
TIMEOUT_SECONDS = 3.0


class ForecastServiceUnreachable(RuntimeError):
    """The deployment has a forecast service, and it gave no usable answer."""


def _client() -> ForecastClient | None:
    url = get_tactic_settings().config.forecast_api_url
    return service_client(url, timeout=TIMEOUT_SECONDS) if url else None


def forecast_models() -> ForecastModelCatalog:
    """The service's models; a deployment without the service has none."""
    client = _client()
    if client is None:
        return ForecastModelCatalog(service="not_deployed")
    try:
        return ForecastModelCatalog(service="available", models=client.models())
    except (ForecastServiceError, ValueError) as error:
        # A service that answers something else than its contract counts as away.
        logger.warning("event=tactic.forecast_models_unreachable reason=%s", error)
        return ForecastModelCatalog(service="unreachable")


def request_download(model_id: str) -> ForecastModelInfo:
    """Have the service download a model's weights; it answers at once."""
    client = _client()
    if client is None:
        raise ConflictError("This deployment has no forecast service.")
    try:
        return client.request_download(model_id)
    except (ForecastServiceError, ValueError) as error:
        if getattr(error, "status", None) == 404:
            raise NotFoundError(
                f"The forecast service does not offer {model_id}."
            ) from error
        logger.warning("event=tactic.forecast_download_failed reason=%s", error)
        raise ForecastServiceUnreachable(str(error)) from error
