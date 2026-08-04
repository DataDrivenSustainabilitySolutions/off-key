"""Shared RADAR request/response schemas used across backend services."""

from datetime import datetime
from math import ceil
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from off_key_core.models import (
    ADAPTIVE_MODELS_BY_TYPE,
    minimum_model_warmup,
    validate_adaptive_model_params,
)

__all__ = [
    "AdaptivePreprocessingStep",
    "AdaptiveStreamConfig",
    "AdaptiveThresholdConfig",
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
    "ResolvedMonitoringConfig",
    "SimpleJumperMartingaleTrackerConfig",
    "SimpleMixtureMartingaleTrackerConfig",
    "StaticBaselineConfig",
    "StaticMartingaleConfig",
    "resolve_monitoring_strategy_config",
]

_SENSOR_KEY_STRATEGIES = {"full_hierarchy", "top_level", "leaf"}
MonitoringStrategy = Literal["static_baseline", "adaptive_stream"]
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


class StandardScalerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    type: Literal["standard_scaler"] = "standard_scaler"
    with_std: bool = True


class MinMaxScalerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    type: Literal["min_max_scaler"] = "min_max_scaler"
    feature_range: tuple[float, float] = (0.0, 1.0)

    @model_validator(mode="after")
    def validate_range(self) -> "MinMaxScalerConfig":
        if self.feature_range[0] >= self.feature_range[1]:
            raise ValueError("feature_range minimum must be less than maximum")
        return self


class IncrementalPCAConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    type: Literal["incremental_pca"] = "incremental_pca"
    n_components: int = Field(ge=1)
    n0: int = Field(default=50, ge=2, le=1_000_000)
    tol: float = Field(default=1e-7, gt=0, allow_inf_nan=False)
    forgetting_factor: float | None = Field(default=None, gt=0, lt=1)

    @model_validator(mode="after")
    def validate_initialization(self) -> "IncrementalPCAConfig":
        if self.n0 < self.n_components:
            raise ValueError("n0 must be at least n_components")
        return self


class RandomProjectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    type: Literal["random_projection"] = "random_projection"
    n_components: int = Field(ge=1)
    seed: int | None = None


AdaptivePreprocessingStep = Annotated[
    StandardScalerConfig
    | MinMaxScalerConfig
    | IncrementalPCAConfig
    | RandomProjectionConfig,
    Field(discriminator="type"),
]


class AdaptiveThresholdConfig(BaseModel):
    """Frozen empirical quantile threshold resolved after calibration."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    mode: Literal["calibrated_quantile"] = "calibrated_quantile"
    quantile: float = Field(default=1.0, gt=0, le=1, allow_inf_nan=False)


class AdaptiveStreamConfig(BaseModel):
    """Configuration for score-then-learn adaptive stream monitoring."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    model_type: str = "aberrant_online_isolation_forest"
    model_params: dict[str, Any] = Field(default_factory=dict)
    training_window_size: int = Field(default=1200, ge=2, le=1_000_000)
    calibration_window_size: int = Field(default=360, ge=1, le=1_000_000)
    preprocessing_steps: list[AdaptivePreprocessingStep] = Field(
        default_factory=list,
        max_length=2,
    )
    threshold_config: AdaptiveThresholdConfig = Field(
        default_factory=AdaptiveThresholdConfig
    )

    @field_validator("model_type")
    @classmethod
    def normalize_model_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("model_type must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_pipeline(self) -> "AdaptiveStreamConfig":
        object.__setattr__(
            self,
            "model_params",
            validate_adaptive_model_params(self.model_type, self.model_params),
        )
        scalers = {"standard_scaler", "min_max_scaler"}
        projections = {"incremental_pca", "random_projection"}
        types = [step.type for step in self.preprocessing_steps]
        if sum(step_type in scalers for step_type in types) > 1:
            raise ValueError("At most one scaler may be configured")
        if sum(step_type in projections for step_type in types) > 1:
            raise ValueError("At most one projection may be configured")
        if (
            types
            and types[0] in projections
            and any(step_type in scalers for step_type in types[1:])
        ):
            raise ValueError("A scaler must precede the projection")
        required_warmup = minimum_model_warmup(self.model_type, self.model_params)
        for step in self.preprocessing_steps:
            if isinstance(step, IncrementalPCAConfig):
                required_warmup = max(required_warmup, step.n0)
        if self.training_window_size < required_warmup:
            raise ValueError(
                "training_window_size must cover the configured model and "
                f"preprocessing warm-up ({required_warmup})"
            )
        return self

    def effective_feature_count(self, input_feature_count: int) -> int:
        if input_feature_count < 1:
            raise ValueError("At least one input feature is required")
        feature_count = input_feature_count
        for step in self.preprocessing_steps:
            if isinstance(step, IncrementalPCAConfig | RandomProjectionConfig):
                if step.n_components > feature_count:
                    raise ValueError(
                        "n_components must not exceed the incoming feature count"
                    )
                feature_count = step.n_components
        return feature_count

    def validate_feature_schema(self, feature_keys: list[str]) -> int:
        """Validate model compatibility against the canonical aligned schema."""
        if not feature_keys or len(feature_keys) != len(set(feature_keys)):
            raise ValueError("Adaptive feature keys must be non-empty and unique")
        feature_count = self.effective_feature_count(len(feature_keys))
        requirement = ADAPTIVE_MODELS_BY_TYPE[self.model_type].feature_count
        if requirement == "one" and feature_count != 1:
            raise ValueError("Selected adaptive model requires exactly one feature")
        if requirement == "two" and feature_count != 2:
            raise ValueError("Selected adaptive model requires exactly two features")
        return feature_count


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


class ResolvedMonitoringConfig(BaseModel):
    """Canonical strategy configuration shared by Gateway, TACTIC, and RADAR."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy: MonitoringStrategy
    model_type: str
    model_params: dict[str, Any]
    static_baseline_config: StaticBaselineConfig | None = None
    adaptive_stream_config: AdaptiveStreamConfig | None = None


def resolve_monitoring_strategy_config(
    *,
    strategy: MonitoringStrategy,
    model_type: str | None,
    model_params: dict[str, Any] | None,
    static_baseline_config: StaticBaselineConfig | dict[str, Any] | None,
    adaptive_stream_config: AdaptiveStreamConfig | dict[str, Any] | None,
) -> ResolvedMonitoringConfig:
    """Resolve strategy defaults and enforce compatibility-mirror invariants."""
    if strategy == "adaptive_stream":
        return _resolve_adaptive_monitoring_config(
            model_type=model_type,
            model_params=model_params,
            static_baseline_config=static_baseline_config,
            adaptive_stream_config=adaptive_stream_config,
        )

    return _resolve_static_monitoring_config(
        model_type=model_type,
        model_params=model_params,
        static_baseline_config=static_baseline_config,
        adaptive_stream_config=adaptive_stream_config,
    )


def _resolve_adaptive_monitoring_config(
    *,
    model_type: str | None,
    model_params: dict[str, Any] | None,
    static_baseline_config: StaticBaselineConfig | dict[str, Any] | None,
    adaptive_stream_config: AdaptiveStreamConfig | dict[str, Any] | None,
) -> ResolvedMonitoringConfig:
    if static_baseline_config is not None:
        raise ValueError("static_baseline_config is not valid for adaptive_stream")
    if adaptive_stream_config is None:
        adaptive = AdaptiveStreamConfig(
            model_type=model_type or "aberrant_online_isolation_forest",
            model_params=model_params or {},
        )
    else:
        adaptive = (
            adaptive_stream_config
            if isinstance(adaptive_stream_config, AdaptiveStreamConfig)
            else AdaptiveStreamConfig(**adaptive_stream_config)
        )
    if model_type is not None and model_type != adaptive.model_type:
        raise ValueError("model_type conflicts with adaptive_stream_config.model_type")
    if model_params is not None:
        normalized_params = validate_adaptive_model_params(
            adaptive.model_type, model_params
        )
        if normalized_params != adaptive.model_params:
            raise ValueError(
                "model_params conflicts with adaptive_stream_config.model_params"
            )
    return ResolvedMonitoringConfig(
        strategy="adaptive_stream",
        model_type=adaptive.model_type,
        model_params=adaptive.model_params,
        adaptive_stream_config=adaptive,
    )


def _resolve_static_monitoring_config(
    *,
    model_type: str | None,
    model_params: dict[str, Any] | None,
    static_baseline_config: StaticBaselineConfig | dict[str, Any] | None,
    adaptive_stream_config: AdaptiveStreamConfig | dict[str, Any] | None,
) -> ResolvedMonitoringConfig:
    if adaptive_stream_config is not None:
        raise ValueError("adaptive_stream_config is not valid for static_baseline")
    if static_baseline_config is None:
        static = StaticBaselineConfig(
            model_type=model_type or "pyod_iforest",
            model_params=model_params or {},
        )
    else:
        static = (
            static_baseline_config
            if isinstance(static_baseline_config, StaticBaselineConfig)
            else StaticBaselineConfig(**static_baseline_config)
        )
    if model_type is not None and model_type != static.model_type:
        raise ValueError("model_type conflicts with static_baseline_config.model_type")
    if model_params is not None and model_params != static.model_params:
        raise ValueError(
            "model_params conflicts with static_baseline_config.model_params"
        )
    return ResolvedMonitoringConfig(
        strategy="static_baseline",
        model_type=static.model_type,
        model_params=static.model_params,
        static_baseline_config=static,
    )
