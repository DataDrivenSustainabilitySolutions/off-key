"""Shared RADAR request/response schemas used across backend services."""

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "AdaptiveStreamConfig",
    "FdrConfig",
    "MonitoringStrategy",
    "PerformanceConfig",
    "StaticBaselineConfig",
]

_SENSOR_KEY_STRATEGIES = {"full_hierarchy", "top_level", "leaf"}
_ALIGNMENT_MODES = {"strict_barrier"}
MonitoringStrategy = Literal["static_baseline", "adaptive_stream"]


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


class FdrConfig(BaseModel):
    """Online FDR settings for conformal p-value streams."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    method: Literal["saffron", "naive"] = "saffron"
    alpha: float = Field(default=0.05, gt=0.0, lt=1.0)
    wealth: float | None = Field(default=None, gt=0.0, lt=1.0)
    lambda_: float = Field(default=0.5, gt=0.0, lt=1.0)
    cutoff: float = Field(default=0.05, gt=0.0, lt=1.0)

    @model_validator(mode="after")
    def validate_saffron_settings(self) -> Self:
        if (
            self.method == "saffron"
            and self.wealth is not None
            and self.wealth >= self.alpha
        ):
            raise ValueError("wealth must be less than alpha for SAFFRON")
        return self

    @property
    def resolved_wealth(self) -> float:
        """Return configured wealth or the default SAFFRON half-alpha wealth."""
        return self.wealth if self.wealth is not None else self.alpha / 2.0

    @property
    def effective_threshold(self) -> float:
        """Return the configured rejection threshold for the selected FDR method."""
        return self.cutoff if self.method == "naive" else self.alpha


class StaticBaselineConfig(BaseModel):
    """Configuration for static baseline conformal monitoring."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    model_type: str = "pyod_iforest"
    model_params: dict[str, Any] = Field(default_factory=dict)
    training_window_size: int = Field(default=1200, ge=20, le=1_000_000)
    calibration_fraction: float = Field(default=0.3, gt=0.0, lt=0.95)
    conformal_strategy: Literal["split"] = "split"
    seed: int | None = 42
    fdr_config: FdrConfig = Field(default_factory=FdrConfig)

    @field_validator("model_type")
    @classmethod
    def validate_static_model_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("model_type must not be empty")
        return normalized


class AdaptiveStreamConfig(BaseModel):
    """Configuration for adaptive/non-static streaming monitoring."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    model_type: str = "knn"
    model_params: dict[str, Any] = Field(default_factory=dict)
    preprocessing_steps: list[dict[str, Any]] = Field(default_factory=list)
    performance_config: PerformanceConfig = Field(default_factory=PerformanceConfig)

    @field_validator("model_type")
    @classmethod
    def validate_adaptive_model_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("model_type must not be empty")
        return normalized
