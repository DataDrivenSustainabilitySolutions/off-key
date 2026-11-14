import os
import socket
import uuid

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .worker import PoolOptions


def _worker_id() -> str:
    # A restarted replica is a new worker, so a lease it held before is never
    # mistaken for its own.
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


class RadarPoolSettings(BaseSettings):
    """The pool reads RADAR's database settings; these size and pace it."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    # The image this replica runs; it claims only workloads pinned to it.
    RADAR_POOL_RUNTIME: str = Field(min_length=1, max_length=512)
    RADAR_POOL_WORKER_ID: str = Field(default_factory=_worker_id, min_length=1)
    # Workloads one replica runs at once; scale replicas for more.
    RADAR_POOL_CAPACITY: int = Field(default=8, ge=1, le=256)
    RADAR_POOL_POLL_SECONDS: float = Field(default=2.0, gt=0, le=30)
    RADAR_POOL_LEASE_SECONDS: float = Field(default=30.0, ge=5, le=600)
    RADAR_POOL_STOP_TIMEOUT_SECONDS: float = Field(default=20.0, gt=0, le=300)
    RADAR_POOL_RESTART_BACKOFF_SECONDS: float = Field(default=5.0, gt=0, le=300)
    # A monitor that crashes this often within the window is left failed.
    RADAR_POOL_MAX_RESTARTS: int = Field(default=5, ge=1, le=100)
    RADAR_POOL_RESTART_WINDOW_SECONDS: float = Field(default=900.0, ge=60)
    RADAR_POOL_HEALTH_PORT: int = Field(default=8030, ge=1, le=65535)
    # Workload kinds this replica claims, comma-separated.
    RADAR_POOL_KINDS: str = "monitor,preflight"

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(k.strip() for k in self.RADAR_POOL_KINDS.split(",") if k.strip())

    @model_validator(mode="after")
    def validate_lease_window(self) -> "RadarPoolSettings":
        # The worker renews every poll and fences itself at half the lease.
        if self.RADAR_POOL_POLL_SECONDS * 4 > self.RADAR_POOL_LEASE_SECONDS:
            raise ValueError(
                "RADAR_POOL_LEASE_SECONDS must be at least four polls long"
            )
        if not self.kinds or not set(self.kinds) <= {"monitor", "preflight"}:
            raise ValueError("RADAR_POOL_KINDS names only monitor and preflight")
        return self

    def options(self) -> PoolOptions:
        return PoolOptions(
            worker_id=self.RADAR_POOL_WORKER_ID,
            runtime=self.RADAR_POOL_RUNTIME,
            capacity=self.RADAR_POOL_CAPACITY,
            poll_seconds=self.RADAR_POOL_POLL_SECONDS,
            lease_seconds=self.RADAR_POOL_LEASE_SECONDS,
            stop_timeout_seconds=self.RADAR_POOL_STOP_TIMEOUT_SECONDS,
            restart_backoff_seconds=self.RADAR_POOL_RESTART_BACKOFF_SECONDS,
            max_restarts=self.RADAR_POOL_MAX_RESTARTS,
            restart_window_seconds=self.RADAR_POOL_RESTART_WINDOW_SECONDS,
            kinds=self.kinds,
        )
