"""Validation and numeric coercion for incoming telemetry features."""

import math
from typing import Any

_MAX_ABSOLUTE_FEATURE_VALUE = 1e10
_MAX_FEATURE_NAME_LENGTH = 100
_METADATA_FEATURE_KEYS = frozenset(
    {
        "timestamp",
        "time",
        "datetime",
        "date",
        "created",
        "created_at",
        "updated_at",
        "ingested_at",
    }
)


class TelemetryFeatureValidator:
    """Keep bounded, finite numeric telemetry and discard metadata."""

    def __init__(
        self,
        max_feature_count: int = 100,
        max_string_length: int = 1000,
    ) -> None:
        self.max_feature_count = max_feature_count
        self.max_string_length = max_string_length

    def validate_and_sanitize(self, data: dict[str, Any]) -> dict[str, float]:
        if not isinstance(data, dict):
            raise TypeError("Input must be a dictionary")
        if len(data) > self.max_feature_count:
            raise ValueError(
                f"Too many features: {len(data)} > {self.max_feature_count}"
            )

        sanitized: dict[str, float] = {}
        for key, value in data.items():
            if (
                not isinstance(key, str)
                or len(key) > _MAX_FEATURE_NAME_LENGTH
                or key.lower() in _METADATA_FEATURE_KEYS
            ):
                continue
            numeric_value = self._coerce_numeric(value)
            if numeric_value is not None:
                sanitized[key] = numeric_value
        return sanitized

    def _coerce_numeric(self, value: Any) -> float | None:
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            if len(value) > self.max_string_length:
                return None
            try:
                value = float(value)
            except ValueError:
                return None
        elif isinstance(value, int | float):
            value = float(value)
        else:
            return None

        if math.isfinite(value) and abs(value) < _MAX_ABSOLUTE_FEATURE_VALUE:
            return value
        return None
