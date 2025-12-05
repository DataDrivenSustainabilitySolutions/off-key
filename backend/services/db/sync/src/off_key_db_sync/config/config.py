"""
Database Sync Service Configuration

Handles configuration for the database sync service including sync intervals,
batch processing, health monitoring, and charger cleanup.
"""

from pydantic import BaseModel, field_validator, model_validator
from pydantic_settings import BaseSettings
from typing import Self
from dotenv import find_dotenv, load_dotenv
from .core_config import get_retention_days

# Load default ".env" file from upper project tree
load_dotenv()

# Override with dev.env values if present
dev_env = find_dotenv("dev.env")
if dev_env:
    load_dotenv(dev_env, override=True)


class SyncConfig(BaseModel):
    """
    Database Sync service configuration with business logic validation.

    This is a pure data model containing validated configuration values
    for the database sync service.
    """

    # Service Control
    enabled: bool
    sync_on_startup: bool

    # Sync Intervals (in seconds)
    chargers_interval: int
    telemetry_interval: int
    telemetry_limit: int
    enable_gap_detection: bool  # Check for existing data and sync only gaps
    enable_incremental_sync: bool  # Use date parameters for incremental sync
    enable_pagination: bool  # Handle API pagination for large datasets
    max_pagination_calls: int  # Maximum number of pagination calls per hierarchy
    retention_days: int  # Days of telemetry data to retain (14 = 2 weeks)

    # API Server Configuration
    api_host: str
    api_port: int

    # Charger Cleanup Configuration
    cleanup_enabled: bool
    cleanup_days_inactive: int
    cleanup_interval: int  # in seconds

    # Batch Processing Configuration
    batch_size_small: int
    batch_size_medium: int
    batch_size_large: int

    # Health Check Thresholds
    charger_sync_success_rate_unhealthy: float
    charger_sync_success_rate_degraded: float
    charger_sync_latency_unhealthy: float
    charger_sync_latency_degraded: float

    telemetry_sync_success_rate_unhealthy: float
    telemetry_sync_success_rate_degraded: float
    telemetry_batch_success_rate_unhealthy: float
    telemetry_batch_success_rate_degraded: float
    telemetry_sync_latency_unhealthy: float
    telemetry_sync_latency_degraded: float

    # Scheduler Configuration
    scheduler_misfire_grace_time: int
    scheduler_max_instances: int

    class Config:
        # Prevent extra fields
        extra = "forbid"
        # Validate assignment to ensure changes maintain constraints
        validate_assignment = True

    @field_validator("api_port")
    @classmethod
    def validate_api_port(cls, v: int) -> int:
        """Validate API port is in valid range"""
        if not 1 <= v <= 65535:
            raise ValueError("API port must be between 1 and 65535")
        return v

    @field_validator("chargers_interval")
    @classmethod
    def validate_chargers_interval(cls, v: int) -> int:
        """Validate charger sync interval"""
        if v < 0:
            raise ValueError(
                "Charger sync interval must be non-negative (0 to disable)"
            )
        if v > 0 and v < 60:
            raise ValueError(
                "Charger sync interval must be at least 60 seconds when enabled"
            )
        return v

    @field_validator("telemetry_interval")
    @classmethod
    def validate_telemetry_interval(cls, v: int) -> int:
        """Validate telemetry sync interval"""
        if v < 0:
            raise ValueError(
                "Telemetry sync interval must be non-negative (0 to disable)"
            )
        if v > 0 and v < 300:
            raise ValueError(
                "Telemetry sync interval must be at least 300 seconds "
                "(5 minutes) when enabled"
            )
        return v

    @field_validator("telemetry_limit")
    @classmethod
    def validate_telemetry_limit(cls, v: int) -> int:
        """Validate telemetry record limit"""
        if not 1 <= v <= 100000:
            raise ValueError("Telemetry limit must be between 1 and 100,000")
        return v

    @field_validator("max_pagination_calls")
    @classmethod
    def validate_max_pagination_calls(cls, v: int) -> int:
        """Validate maximum pagination calls"""
        if not 1 <= v <= 100:
            raise ValueError("Max pagination calls must be between 1 and 100")
        return v

    @field_validator("retention_days")
    @classmethod
    def validate_retention_days(cls, v: int) -> int:
        """Validate retention period"""
        if not 1 <= v <= 365:
            raise ValueError("Retention days must be between 1 and 365")
        return v

    @field_validator("cleanup_days_inactive")
    @classmethod
    def validate_cleanup_days_inactive(cls, v: int) -> int:
        """Validate cleanup days threshold"""
        if v != -1 and not 1 <= v <= 3650:
            raise ValueError(
                "Cleanup days inactive must be between 1 and 3650, or -1 to delete all"
            )
        return v

    @field_validator("cleanup_interval")
    @classmethod
    def validate_cleanup_interval(cls, v: int) -> int:
        """Validate cleanup interval"""
        if v < 0:
            raise ValueError("Cleanup interval must be non-negative (0 to disable)")
        if v > 0 and v < 3600:
            raise ValueError(
                "Cleanup interval must be at least 3600 seconds (1 hour) when enabled"
            )
        return v

    @field_validator("batch_size_small", "batch_size_medium", "batch_size_large")
    @classmethod
    def validate_batch_size(cls, v: int) -> int:
        """Validate batch size"""
        if not 1 <= v <= 50000:
            raise ValueError("Batch size must be between 1 and 50,000")
        return v

    @field_validator("scheduler_misfire_grace_time")
    @classmethod
    def validate_misfire_grace_time(cls, v: int) -> int:
        """Validate scheduler misfire grace time"""
        if not 60 <= v <= 3600:
            raise ValueError("Misfire grace time must be between 60 and 3600 seconds")
        return v

    @field_validator("scheduler_max_instances")
    @classmethod
    def validate_max_instances(cls, v: int) -> int:
        """Validate scheduler max instances"""
        if not 1 <= v <= 5:
            raise ValueError("Scheduler max instances must be between 1 and 5")
        return v

    @field_validator(
        "charger_sync_success_rate_unhealthy",
        "charger_sync_success_rate_degraded",
        "telemetry_sync_success_rate_unhealthy",
        "telemetry_sync_success_rate_degraded",
        "telemetry_batch_success_rate_unhealthy",
        "telemetry_batch_success_rate_degraded",
    )
    @classmethod
    def validate_success_rate(cls, v: float) -> float:
        """Validate success rate thresholds"""
        if not 0.0 <= v <= 100.0:
            raise ValueError("Success rate must be between 0.0 and 100.0")
        return v

    @field_validator(
        "charger_sync_latency_unhealthy",
        "charger_sync_latency_degraded",
        "telemetry_sync_latency_unhealthy",
        "telemetry_sync_latency_degraded",
    )
    @classmethod
    def validate_latency(cls, v: float) -> float:
        """Validate latency thresholds"""
        if not 1.0 <= v <= 3600.0:
            raise ValueError("Latency threshold must be between 1.0 and 3600.0 seconds")
        return v

    @model_validator(mode="after")
    def validate_threshold_consistency(self) -> Self:
        """Validate that health thresholds are consistent"""
        # Charger sync thresholds
        if (
            self.charger_sync_success_rate_degraded
            <= self.charger_sync_success_rate_unhealthy
        ):
            raise ValueError(
                f"Charger sync degraded threshold "
                f"({self.charger_sync_success_rate_degraded}%) "
                f"must be greater than unhealthy threshold "
                f"({self.charger_sync_success_rate_unhealthy}%)"
            )

        if self.charger_sync_latency_degraded >= self.charger_sync_latency_unhealthy:
            raise ValueError(
                f"Charger sync degraded latency "
                f"({self.charger_sync_latency_degraded}s) "
                f"must be less than unhealthy latency "
                f"({self.charger_sync_latency_unhealthy}s)"
            )

        # Telemetry sync thresholds
        if (
            self.telemetry_sync_success_rate_degraded
            <= self.telemetry_sync_success_rate_unhealthy
        ):
            raise ValueError(
                f"Telemetry sync degraded threshold "
                f"({self.telemetry_sync_success_rate_degraded}%) "
                f"must be greater than unhealthy threshold "
                f"({self.telemetry_sync_success_rate_unhealthy}%)"
            )

        if (
            self.telemetry_batch_success_rate_degraded
            <= self.telemetry_batch_success_rate_unhealthy
        ):
            raise ValueError(
                f"Telemetry batch degraded threshold "
                f"({self.telemetry_batch_success_rate_degraded}%) "
                f"must be greater than unhealthy threshold "
                f"({self.telemetry_batch_success_rate_unhealthy}%)"
            )

        if (
            self.telemetry_sync_latency_degraded
            >= self.telemetry_sync_latency_unhealthy
        ):
            raise ValueError(
                f"Telemetry sync degraded latency "
                f"({self.telemetry_sync_latency_degraded}s) "
                f"must be less than unhealthy latency "
                f"({self.telemetry_sync_latency_unhealthy}s)"
            )

        # Batch size consistency
        if self.batch_size_medium <= self.batch_size_small:
            raise ValueError(
                f"Medium batch size ({self.batch_size_medium}) "
                f"must be greater than small batch size ({self.batch_size_small})"
            )

        if self.batch_size_large <= self.batch_size_medium:
            raise ValueError(
                f"Large batch size ({self.batch_size_large}) "
                f"must be greater than medium batch size ({self.batch_size_medium})"
            )

        return self


class SyncSettings(BaseSettings):
    """
    Database Sync Service Settings

    Environment variable parsing for the database sync service.
    Follows the dual-config pattern where this class handles environment
    parsing and SyncConfig handles business logic validation.
    """

    # Service Control
    SYNC_ENABLED: bool = True  # Enable background sync service
    SYNC_ON_STARTUP: bool = True  # Run sync immediately on startup

    # Sync Intervals
    SYNC_CHARGERS_INTERVAL: int = (
        3600  # Charger sync interval (seconds) - default 1 hour
    )
    SYNC_TELEMETRY_INTERVAL: int = (
        21600  # Telemetry sync interval (seconds) - default 6 hours
    )
    SYNC_TELEMETRY_LIMIT: int = 10000  # Max telemetry records per hierarchy
    SYNC_ENABLE_GAP_DETECTION: bool = True  # Enable gap detection for telemetry sync
    SYNC_ENABLE_INCREMENTAL_SYNC: bool = (
        True  # Use date parameters for incremental sync
    )
    SYNC_ENABLE_PAGINATION: bool = True  # Handle API pagination for large datasets
    SYNC_MAX_PAGINATION_CALLS: int = 10  # Maximum pagination calls per hierarchy

    # API Server Configuration
    SYNC_API_HOST: str = "0.0.0.0"  # API server host
    SYNC_API_PORT: int = 8009  # API server port

    # Charger Cleanup Configuration
    SYNC_CLEANUP_ENABLED: bool = False  # Enable automatic charger cleanup
    SYNC_CLEANUP_DAYS_INACTIVE: int = 90  # Days of inactivity before cleanup
    SYNC_CLEANUP_INTERVAL: int = 604800  # Cleanup interval (seconds) - default weekly

    # Batch Processing Configuration
    SYNC_BATCH_SIZE_SMALL: int = 1000  # Single batch threshold
    SYNC_BATCH_SIZE_MEDIUM: int = 2000  # Medium dataset batch size
    SYNC_BATCH_SIZE_LARGE: int = 5000  # Large dataset batch size

    # Health Check Thresholds - Charger Sync
    SYNC_CHARGER_SUCCESS_RATE_UNHEALTHY: float = 50.0  # % below = unhealthy
    SYNC_CHARGER_SUCCESS_RATE_DEGRADED: float = 80.0  # % below = degraded
    SYNC_CHARGER_LATENCY_UNHEALTHY: float = 60.0  # seconds above = unhealthy
    SYNC_CHARGER_LATENCY_DEGRADED: float = 30.0  # seconds above = degraded

    # Health Check Thresholds - Telemetry Sync
    SYNC_TELEMETRY_SUCCESS_RATE_UNHEALTHY: float = 50.0  # % below = unhealthy
    SYNC_TELEMETRY_SUCCESS_RATE_DEGRADED: float = 80.0  # % below = degraded
    SYNC_TELEMETRY_BATCH_SUCCESS_RATE_UNHEALTHY: float = 90.0  # % below = unhealthy
    SYNC_TELEMETRY_BATCH_SUCCESS_RATE_DEGRADED: float = 95.0  # % below = degraded
    SYNC_TELEMETRY_LATENCY_UNHEALTHY: float = 300.0  # seconds above = unhealthy (5 min)
    SYNC_TELEMETRY_LATENCY_DEGRADED: float = 120.0  # seconds above = degraded (2 min)

    # Scheduler Configuration
    SYNC_SCHEDULER_MISFIRE_GRACE_TIME: int = (
        300  # Scheduler misfire grace time (seconds)
    )
    SYNC_SCHEDULER_MAX_INSTANCES: int = 1  # Max concurrent instances per job

    @property
    def config(self) -> SyncConfig:
        """
        Create SyncConfig instance from environment settings.

        This property demonstrates the dual-config pattern: environment parsing
        happens here, while business logic validation occurs in SyncConfig.

        Returns:
            SyncConfig: Validated sync service config with business logic constraints
        """
        return SyncConfig(
            enabled=self.SYNC_ENABLED,
            sync_on_startup=self.SYNC_ON_STARTUP,
            chargers_interval=self.SYNC_CHARGERS_INTERVAL,
            telemetry_interval=self.SYNC_TELEMETRY_INTERVAL,
            telemetry_limit=self.SYNC_TELEMETRY_LIMIT,
            enable_gap_detection=self.SYNC_ENABLE_GAP_DETECTION,
            enable_incremental_sync=self.SYNC_ENABLE_INCREMENTAL_SYNC,
            enable_pagination=self.SYNC_ENABLE_PAGINATION,
            max_pagination_calls=self.SYNC_MAX_PAGINATION_CALLS,
            retention_days=get_retention_days(),  # Use centralized config
            api_host=self.SYNC_API_HOST,
            api_port=self.SYNC_API_PORT,
            cleanup_enabled=self.SYNC_CLEANUP_ENABLED,
            cleanup_days_inactive=self.SYNC_CLEANUP_DAYS_INACTIVE,
            cleanup_interval=self.SYNC_CLEANUP_INTERVAL,
            batch_size_small=self.SYNC_BATCH_SIZE_SMALL,
            batch_size_medium=self.SYNC_BATCH_SIZE_MEDIUM,
            batch_size_large=self.SYNC_BATCH_SIZE_LARGE,
            charger_sync_success_rate_unhealthy=self.SYNC_CHARGER_SUCCESS_RATE_UNHEALTHY,
            charger_sync_success_rate_degraded=self.SYNC_CHARGER_SUCCESS_RATE_DEGRADED,
            charger_sync_latency_unhealthy=self.SYNC_CHARGER_LATENCY_UNHEALTHY,
            charger_sync_latency_degraded=self.SYNC_CHARGER_LATENCY_DEGRADED,
            telemetry_sync_success_rate_unhealthy=self.SYNC_TELEMETRY_SUCCESS_RATE_UNHEALTHY,
            telemetry_sync_success_rate_degraded=self.SYNC_TELEMETRY_SUCCESS_RATE_DEGRADED,
            telemetry_batch_success_rate_unhealthy=self.SYNC_TELEMETRY_BATCH_SUCCESS_RATE_UNHEALTHY,
            telemetry_batch_success_rate_degraded=self.SYNC_TELEMETRY_BATCH_SUCCESS_RATE_DEGRADED,
            telemetry_sync_latency_unhealthy=self.SYNC_TELEMETRY_LATENCY_UNHEALTHY,
            telemetry_sync_latency_degraded=self.SYNC_TELEMETRY_LATENCY_DEGRADED,
            scheduler_misfire_grace_time=self.SYNC_SCHEDULER_MISFIRE_GRACE_TIME,
            scheduler_max_instances=self.SYNC_SCHEDULER_MAX_INSTANCES,
        )


sync_settings = SyncSettings()
