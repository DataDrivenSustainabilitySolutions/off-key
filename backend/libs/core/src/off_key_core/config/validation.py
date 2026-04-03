from __future__ import annotations

from typing import Any, Callable, Iterable

from pydantic import ValidationError

ALLOWED_ENVIRONMENTS: frozenset[str] = frozenset(
    {"development", "test", "staging", "production"}
)


def validate_environment(value: str) -> str:
    """Normalise and validate an ENVIRONMENT setting value.

    Intended for use inside Pydantic @field_validator methods:

        @field_validator("ENVIRONMENT")
        @classmethod
        def validate_environment(cls, value: str) -> str:
            return _validate_environment(value)
    """
    normalized = value.strip().lower()
    if normalized not in ALLOWED_ENVIRONMENTS:
        allowed = ", ".join(sorted(ALLOWED_ENVIRONMENTS))
        raise ValueError(f"ENVIRONMENT must be one of: {allowed}")
    return normalized


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
            for detail in _format_validation_error(exc):
                lines.append(f"{name}: {detail}")
        else:
            lines.append(f"{name}: {exc}")

    raise RuntimeError("\n".join(lines))
