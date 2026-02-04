"""Startup configuration validation helpers."""

from __future__ import annotations

from typing import Any, Callable, Iterable

from pydantic import ValidationError


def _format_validation_error(error: ValidationError) -> list[str]:
    """Format pydantic ValidationError into readable lines."""
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
    """Validate that required settings can be loaded at startup.

    Args:
        specs: Iterable of (name, getter) pairs.
        context: Context string used in error messages.

    Raises:
        RuntimeError: If any settings fail to load/validate.
    """
    failures: list[tuple[str, Exception]] = []
    for name, getter in specs:
        try:
            getter()
        except Exception as exc:
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
