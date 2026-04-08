"""Shared RADAR request/response schemas used across backend services."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = ["PerformanceConfig"]

_SENSOR_KEY_STRATEGIES = {"full_hierarchy", "top_level", "leaf"}
_ALIGNMENT_MODES = {"strict_barrier"}


class PerformanceConfig(BaseModel):
    """Performance and multivariate alignment options for RADAR workloads."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    heuristic_enabled: bool = True
    heuristic_window_size: int = Field(default=300, ge=3, le=100000)
    heuristic_min_samples: int = Field(default=30, ge=2, le=100000)
    heuristic_tail_alpha: float = Field(default=0.005, gt=0.0, lt=1.0)
    alignment_mode: str = "strict_barrier"
    sensor_key_strategy: str = "full_hierarchy"
    sensor_freshness_seconds: float = Field(default=30.0, gt=0.0)

    @field_validator("sensor_key_strategy")
    @classmethod
    def validate_sensor_key_strategy(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _SENSOR_KEY_STRATEGIES:
            allowed = ", ".join(sorted(_SENSOR_KEY_STRATEGIES))
            raise ValueError(f"sensor_key_strategy must be one of: {allowed}")
        return normalized

    @field_validator("alignment_mode")
    @classmethod
    def validate_alignment_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _ALIGNMENT_MODES:
            allowed = ", ".join(sorted(_ALIGNMENT_MODES))
            raise ValueError(f"alignment_mode must be one of: {allowed}")
        return normalized

    @model_validator(mode="after")
    def validate_heuristic_settings(self) -> Self:
        if self.heuristic_min_samples > self.heuristic_window_size:
            raise ValueError(
                "heuristic_min_samples must be <= heuristic_window_size "
                f"(got {self.heuristic_min_samples} > {self.heuristic_window_size})"
            )
        return self
