"""Shared RADAR request/response schemas used across backend services."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "MonitoringStrategy",
    "PerformanceConfig",
    "RadarOperationalProgress",
    "RadarOperationalStage",
    "RadarOperationalStatus",
    "StaticMartingaleConfig",
    "StaticBaselineConfig",
]

_SENSOR_KEY_STRATEGIES = {"full_hierarchy", "top_level", "leaf"}
_ALIGNMENT_MODES = {"strict_barrier"}
MonitoringStrategy = Literal["static_baseline"]
RadarOperationalStage = Literal[
    "starting",
    "waiting_for_data",
    "collecting_training",
    "collecting_calibration",
    "training",
    "operational",
    "degraded",
    "failed",
    "stopped",
]


class RadarOperationalProgress(BaseModel):
    """Progress toward a bounded RADAR operational stage."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    current: int = Field(default=0, ge=0)
    target: int = Field(gt=0)


class RadarOperationalStatus(BaseModel):
    """Current runtime stage reported by a RADAR workload."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    stage: RadarOperationalStage = "starting"
    detail: str | None = None
    progress: RadarOperationalProgress | None = None
    message_count: int = Field(default=0, ge=0)
    processed_message_count: int = Field(default=0, ge=0)
    last_alignment_status: str | None = None
    error: str | None = None
    updated_at: datetime | None = None
    is_stale: bool = False


class PerformanceConfig(BaseModel):
    """Performance and multivariate alignment options for RADAR workloads."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

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


class StaticMartingaleConfig(BaseModel):
    """Native restarted-mixture alarm settings for static monitoring."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    method: Literal["power"] = "power"
    epsilon: float = Field(default=0.5, gt=0.0, le=1.0)
    restarted_ville_threshold: Literal[100.0] = 100.0


class StaticBaselineConfig(BaseModel):
    """Configuration for static baseline conformal monitoring."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    model_type: str = "pyod_iforest"
    model_params: dict[str, Any] = Field(default_factory=dict)
    training_window_size: int = Field(default=1200, ge=20, le=1_000_000)
    calibration_window_size: int = Field(default=360, ge=1, le=1_000_000)
    calibration_fraction: float = Field(default=0.3, gt=0.0, lt=0.95)
    conformal_strategy: Literal["split"] = "split"
    seed: int | None = 42
    martingale_config: StaticMartingaleConfig = Field(
        default_factory=StaticMartingaleConfig
    )

    @model_validator(mode="before")
    @classmethod
    def populate_legacy_calibration_window(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "calibration_window_size" in data:
            return data

        try:
            training_window_size = int(
                data.get(
                    "training_window_size",
                    cls.model_fields["training_window_size"].default,
                )
            )
            calibration_fraction = float(
                data.get(
                    "calibration_fraction",
                    cls.model_fields["calibration_fraction"].default,
                )
            )
        except (TypeError, ValueError):
            return data

        return {
            **data,
            "calibration_window_size": max(
                1, round(training_window_size * calibration_fraction)
            ),
        }

    @field_validator("model_type")
    @classmethod
    def validate_static_model_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("model_type must not be empty")
        return normalized
