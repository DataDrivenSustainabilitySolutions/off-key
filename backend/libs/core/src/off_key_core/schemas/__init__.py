"""Pydantic schemas for off-key-core."""

from .favorites import FavoriteCreate
from .radar import (
    AlarmStatistic,
    MartingaleTrackerConfig,
    PerformanceConfig,
    PowerMartingaleTrackerConfig,
    RadarOperationalStatus,
    SimpleJumperMartingaleTrackerConfig,
    SimpleMixtureMartingaleTrackerConfig,
    StaticBaselineConfig,
    StaticMartingaleConfig,
)
from .user import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    UserCreate,
    UserLogin,
    UserVerification,
)

__all__ = [
    "AlarmStatistic",
    "FavoriteCreate",
    "ForgotPasswordRequest",
    "MartingaleTrackerConfig",
    "PerformanceConfig",
    "PowerMartingaleTrackerConfig",
    "RadarOperationalStatus",
    "ResetPasswordRequest",
    "SimpleJumperMartingaleTrackerConfig",
    "SimpleMixtureMartingaleTrackerConfig",
    "StaticBaselineConfig",
    "StaticMartingaleConfig",
    "UserCreate",
    "UserLogin",
    "UserVerification",
]
