"""Shared RADAR request/response schemas used across backend services."""

from datetime import datetime
from math import ceil
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = [
    "AlarmStatistic",
    "AutomaticAlarmThresholdConfig",
    "AutomaticThresholdCalibrationConfig",
    "ManualAlarmThresholdConfig",
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
_MAX_AUTOMATIC_CALIBRATION_WORK = 1_000_000_000
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


class ManualAlarmThresholdConfig(BaseModel):
    """Explicit numeric alarm threshold."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    mode: Literal["manual"] = "manual"
    value: float = Field(default=100.0, gt=0.0, allow_inf_nan=False)


class AutomaticAlarmThresholdConfig(BaseModel):
    """Threshold resolved from the configured finite-horizon null target."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    mode: Literal["automatic"] = "automatic"


class AutomaticThresholdCalibrationConfig(BaseModel):
    """Shared family-wise null target for automatically calibrated trackers."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    false_alarm_probability: float = Field(default=0.01, gt=0.0, lt=1.0)
    horizon: int = Field(
        default=1_000,
        ge=10,
        le=100_000,
        description=(
            "Aligned observations per calibrated monitoring window; automatic "
            "tracker state resets before the next window"
        ),
    )
    simulation_count: int = Field(default=5_000, ge=100, le=100_000)

    @model_validator(mode="after")
    def validate_simulation_budget(self) -> "AutomaticThresholdCalibrationConfig":
        if self.horizon * self.simulation_count > 25_000_000:
            raise ValueError("horizon * simulation_count must not exceed 25,000,000")
        return self


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
    threshold_config: Annotated[
        ManualAlarmThresholdConfig | AutomaticAlarmThresholdConfig,
        Field(discriminator="mode"),
    ] = Field(default_factory=ManualAlarmThresholdConfig)

    @model_validator(mode="after")
    def validate_threshold_policy(self) -> "_MartingaleTrackerBase":
        is_ville = self.alarm_statistic in {"martingale", "restarted_martingale"}
        if is_ville and isinstance(
            self.threshold_config, AutomaticAlarmThresholdConfig
        ):
            raise ValueError(
                "Automatic threshold calibration is only available for CUSUM "
                "and Shiryaev-Roberts statistics"
            )
        if (
            is_ville
            and isinstance(self.threshold_config, ManualAlarmThresholdConfig)
            and self.threshold_config.value <= 1.0
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


def _calibration_betting_width(
    tracker: PowerMartingaleTrackerConfig
    | SimpleMixtureMartingaleTrackerConfig
    | SimpleJumperMartingaleTrackerConfig,
) -> int:
    if isinstance(tracker, SimpleMixtureMartingaleTrackerConfig):
        return len(tracker.epsilons) if tracker.epsilons is not None else tracker.n_grid
    if isinstance(tracker, SimpleJumperMartingaleTrackerConfig):
        return 3
    return 1


def _default_martingale_trackers() -> list[PowerMartingaleTrackerConfig]:
    return [PowerMartingaleTrackerConfig(tracker_id="primary")]


class StaticMartingaleConfig(BaseModel):
    """Typed martingale trackers fed by the same conformal p-value stream."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    trackers: list[MartingaleTrackerConfig] = Field(
        default_factory=_default_martingale_trackers,
        min_length=1,
        max_length=16,
    )
    automatic_threshold_calibration: AutomaticThresholdCalibrationConfig = Field(
        default_factory=AutomaticThresholdCalibrationConfig
    )

    @field_validator("trackers")
    @classmethod
    def validate_unique_tracker_ids(
        cls, trackers: list[MartingaleTrackerConfig]
    ) -> list[MartingaleTrackerConfig]:
        tracker_ids = [tracker.tracker_id for tracker in trackers]
        if len(set(tracker_ids)) != len(tracker_ids):
            raise ValueError("tracker_id values must be unique")
        return trackers

    @model_validator(mode="after")
    def validate_automatic_calibration_capacity(self) -> "StaticMartingaleConfig":
        automatic_trackers = [
            tracker
            for tracker in self.trackers
            if isinstance(
                tracker.threshold_config,
                AutomaticAlarmThresholdConfig,
            )
        ]
        automatic_count = len(automatic_trackers)
        if automatic_count == 0:
            return self
        required_simulations = (
            ceil(
                automatic_count
                / self.automatic_threshold_calibration.false_alarm_probability
            )
            - 1
        )
        if self.automatic_threshold_calibration.simulation_count < required_simulations:
            raise ValueError(
                "simulation_count is too small for the family-wise false-alarm "
                f"target; use at least {required_simulations} simulations"
            )
        betting_width = sum(
            _calibration_betting_width(tracker) for tracker in automatic_trackers
        )
        calibration_work = (
            self.automatic_threshold_calibration.horizon
            * self.automatic_threshold_calibration.simulation_count
            * betting_width
        )
        if calibration_work > _MAX_AUTOMATIC_CALIBRATION_WORK:
            raise ValueError(
                "automatic threshold calibration is too computationally large; "
                "reduce the horizon, simulations, automatic trackers, or mixture "
                "grid size"
            )
        return self


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
