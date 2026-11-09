from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Annotated, Any

from pydantic import AfterValidator, ValidationError

ALLOWED_ENVIRONMENTS: frozenset[str] = frozenset(
    {"development", "test", "staging", "production"}
)


# Docker and Swarm secrets; evaluated once at import, before settings classes.
SECRETS_DIR = "/run/secrets" if Path("/run/secrets").is_dir() else None


def validate_environment(value: str) -> str:
    """Normalise and validate an ENVIRONMENT setting value."""
    normalized = value.strip().lower()
    if normalized not in ALLOWED_ENVIRONMENTS:
        allowed = ", ".join(sorted(ALLOWED_ENVIRONMENTS))
        raise ValueError(f"ENVIRONMENT must be one of: {allowed}")
    return normalized


Environment = Annotated[str, AfterValidator(validate_environment)]


def _format_validation_error(error: ValidationError) -> list[str]:
    lines: list[str] = []
    for entry in error.errors():
        location = ".".join(str(item) for item in entry.get("loc", [])) or "<root>"
        message = entry.get("msg", "Invalid value")
        lines.append(f"{location}: {message}")
    if not lines:
        lines.append(str(error))
    return lines


def validate_settings(
    specs: Iterable[tuple[str, Callable[[], Any]]],
    context: str = "settings",
) -> None:
    """Validate settings getters and raise a deterministic aggregated error."""
    failures: list[tuple[str, Exception]] = []
    for name, getter in specs:
        try:
            getter()
        except Exception as exc:  # pragma: no cover - explicit aggregation path
            failures.append((name, exc))

    if not failures:
        return

    lines = [f"{context} validation failed:"]
    for name, exc in failures:
        if isinstance(exc, ValidationError):
            lines.extend(
                f"{name}: {detail}" for detail in _format_validation_error(exc)
            )
        else:
            lines.append(f"{name}: {exc}")

    raise RuntimeError("\n".join(lines))
