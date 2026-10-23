"""One start-up sequence for every long-running service entry point."""

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from off_key_core.config.env import load_env
from off_key_core.config.logs import (
    load_yaml_config,
    log_startup_logging_configuration,
)
from off_key_core.config.validation import validate_settings


def start_service[T](
    name: str,
    logging_yaml: Path | None,
    settings: Iterable[tuple[str, Callable[[], Any]]],
    context: str,
    *,
    after_env: Callable[[], T] | None = None,
) -> T | None:
    """Load the environment, configure logging, then validate settings.

    ``after_env`` runs once the environment is loaded and before logging is
    configured, so a file it loads can also set log levels. Its result is
    returned for the caller to log once logging is ready. Validation runs last,
    so a configuration failure is reported through the structured logger.
    """
    load_env()
    result = after_env() if after_env is not None else None
    load_yaml_config(str(logging_yaml) if logging_yaml else None)
    log_startup_logging_configuration(name)
    validate_settings(settings, context=context)
    return result
