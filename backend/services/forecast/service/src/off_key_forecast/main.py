"""Entry point of the forecast service."""

import tempfile
from pathlib import Path

import uvicorn
from off_key_core.config.bootstrap import start_service
from off_key_core.config.logging import get_logging_settings
from off_key_core.config.logs import logger

from .api import create_app
from .config.config import get_forecast_settings
from .providers import default_providers
from .registry import ModelRegistry


def require_writable_cache(cache_dir: Path) -> None:
    """Refuse to start where downloaded weights could not be kept.

    Otherwise the service looks healthy until the first monitor asks for a
    checkpoint, and that download fails.
    """
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=cache_dir):
            pass
    except OSError as error:
        raise SystemExit(
            f"FORECAST_CACHE_DIR {cache_dir} is not writable: {error}"
        ) from error


def main() -> None:
    start_service(
        "forecast",
        Path(__file__).parent / "config" / "logging.yaml",
        [
            ("logging", get_logging_settings),
            ("forecast", lambda: get_forecast_settings().config),
        ],
        context="Forecast service configuration",
    )
    config = get_forecast_settings().config
    if config.api_token is None:
        logger.warning("event=forecast.no_token the API accepts unauthenticated calls")
    registry = ModelRegistry(default_providers(config), config.cache_dir)
    if any(model.download_bytes for model in registry.models()):
        require_writable_cache(config.cache_dir)
    app = create_app(registry, config.api_token)
    logger.info(
        "event=forecast.start host=%s port=%s models=%s",
        config.api_host,
        config.api_port,
        len(registry.models()),
    )
    try:
        uvicorn.run(app, host=config.api_host, port=config.api_port, log_config=None)
    finally:
        registry.close()
