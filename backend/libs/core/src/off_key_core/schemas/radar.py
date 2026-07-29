"""Shared RADAR request/response schemas used across backend services."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "AlarmStatistic",
    "MartingaleTrackerConfig",
    "MonitoringStrategy",
    "PerformanceConfig",
    "PowerMartingaleTrackerConfig",
    "RadarOperationalProgress",
    "RadarOperationalStage",
    "RadarOperationalStatus",
    "SimpleJumperMartingaleTrackerConfig",
    "SimpleMixtureMartingaleTrackerConfig",
    "StaticBaselineConfig",
    "StaticMartingaleConfig",
]

_SENSOR_KEY_STRATEGIES = {"full_hierarchy", "top_level", "leaf"}
MonitoringStrategy = Literal["static_baseline"]
AlarmStatistic = Literal[
    "martingale",
    "restarted_martingale",
    "cusum",
    "shiryaev_roberts",
]
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
    """Performance options for RADAR workloads."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

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


class _MartingaleTrackerBase(BaseModel):
    """Shared settings for one bounded martingale alarm tracker."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        allow_inf_nan=False,
    )

    tracker_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_-]*$",
    )
    alarm_statistic: AlarmStatistic = "restarted_martingale"
    threshold: float = Field(default=100.0, gt=0.0)

    @model_validator(mode="after")
    def validate_ville_threshold(self) -> "_MartingaleTrackerBase":
        if (
            self.alarm_statistic in {"martingale", "restarted_martingale"}
            and self.threshold <= 1.0
        ):
            raise ValueError("Ville thresholds must be greater than 1")
        return self


class PowerMartingaleTrackerConfig(_MartingaleTrackerBase):
    """Fixed-epsilon power betting tracker."""

    betting_function: Literal["power"] = "power"
    epsilon: float = Field(default=0.5, gt=0.0, le=1.0)


class SimpleMixtureMartingaleTrackerConfig(_MartingaleTrackerBase):
    """Uniform mixture over fixed power-betting epsilon values."""

    betting_function: Literal["simple_mixture"] = "simple_mixture"
    epsilons: list[Annotated[float, Field(gt=0.0, le=1.0)]] | None = Field(
        default=None,
        min_length=1,
        max_length=10_000,
    )
    n_grid: int = Field(default=100, ge=2, le=10_000)
    min_epsilon: float = Field(default=0.01, gt=0.0, le=1.0)


class SimpleJumperMartingaleTrackerConfig(_MartingaleTrackerBase):
    """Simple Jumper adaptive betting tracker."""

    betting_function: Literal["simple_jumper"] = "simple_jumper"
    jump: float = Field(default=0.01, gt=0.0, le=1.0)


MartingaleTrackerConfig = Annotated[
    PowerMartingaleTrackerConfig
    | SimpleMixtureMartingaleTrackerConfig
    | SimpleJumperMartingaleTrackerConfig,
    Field(discriminator="betting_function"),
]


def _default_martingale_trackers() -> list[PowerMartingaleTrackerConfig]:
    return [PowerMartingaleTrackerConfig(tracker_id="primary")]


class StaticMartingaleConfig(BaseModel):
    """Typed martingale trackers fed by the same conformal p-value stream.

    The pre-1.1 flat power/restarted configuration remains accepted and is
    normalized into the primary tracker before validation.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    trackers: list[MartingaleTrackerConfig] = Field(
        default_factory=_default_martingale_trackers,
        min_length=1,
        max_length=16,
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_config(cls, value: Any) -> Any:
        if value is None or isinstance(value, cls):
            return value
        if not isinstance(value, dict) or "trackers" in value:
            return value

        data = dict(value)
        betting_function = data.pop("betting_function", "power")
        alarm_statistic = data.pop("alarm_statistic", "restarted_martingale")
        threshold = data.pop("threshold", data.pop("restarted_ville_threshold", 100.0))
        tracker: dict[str, Any] = {
            "tracker_id": data.pop("tracker_id", "primary"),
            "betting_function": betting_function,
            "alarm_statistic": alarm_statistic,
            "threshold": threshold,
        }
        method_fields = {
            "power": ("epsilon",),
            "simple_mixture": ("epsilons", "n_grid", "min_epsilon"),
            "simple_jumper": ("jump",),
        }
        for field_name in method_fields.get(str(betting_function), ()):
            if field_name in data:
                tracker[field_name] = data.pop(field_name)
        return {"trackers": [tracker], **data}

    @field_validator("trackers")
    @classmethod
    def validate_unique_tracker_ids(
        cls, trackers: list[MartingaleTrackerConfig]
    ) -> list[MartingaleTrackerConfig]:
        tracker_ids = [tracker.tracker_id for tracker in trackers]
        if len(set(tracker_ids)) != len(tracker_ids):
            raise ValueError("tracker_id values must be unique")
        return trackers

    # Compatibility accessors for code that reads the original primary tracker.
    @property
    def betting_function(self) -> str:
        return self.trackers[0].betting_function

    @property
    def alarm_statistic(self) -> AlarmStatistic:
        return self.trackers[0].alarm_statistic

    @property
    def epsilon(self) -> float | None:
        tracker = self.trackers[0]
        return (
            tracker.epsilon
            if isinstance(tracker, PowerMartingaleTrackerConfig)
            else None
        )

    @property
    def restarted_ville_threshold(self) -> float:
        return self.trackers[0].threshold


class StaticBaselineConfig(BaseModel):
    """Configuration for static baseline conformal monitoring."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    model_type: str = "pyod_iforest"
    model_params: dict[str, Any] = Field(default_factory=dict)
    training_window_size: int = Field(default=1200, ge=20, le=1_000_000)
    calibration_window_size: int = Field(default=360, ge=1, le=1_000_000)
    conformal_strategy: Literal["split"] = "split"
    seed: int | None = 42
    martingale_config: StaticMartingaleConfig = Field(
        default_factory=StaticMartingaleConfig
    )

    @field_validator("model_type")
    @classmethod
    def validate_static_model_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("model_type must not be empty")
        return normalized
