import socket

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .worker import WorkerOptions


class DojoWorkerSettings(BaseSettings):
    """The worker reads RADAR's database settings; these tune the replay."""

    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    DOJO_WORKER_ID: str = Field(default_factory=socket.gethostname, min_length=1)
    DOJO_MEMORY_LIMIT_MB: int = Field(default=1024, ge=128, le=16384)
    DOJO_POLL_SECONDS: float = Field(default=2.0, gt=0, le=60)
    DOJO_HEARTBEAT_SECONDS: float = Field(default=10.0, gt=0, le=60)
    # A run whose heartbeat is older than this is failed by the next poll.
    DOJO_STALE_SECONDS: float = Field(default=120.0, ge=30, le=3600)

    @model_validator(mode="after")
    def validate_heartbeat_window(self) -> "DojoWorkerSettings":
        if self.DOJO_HEARTBEAT_SECONDS >= self.DOJO_STALE_SECONDS:
            raise ValueError("DOJO_HEARTBEAT_SECONDS must be below DOJO_STALE_SECONDS")
        return self

    def options(self) -> WorkerOptions:
        return WorkerOptions(
            worker_id=self.DOJO_WORKER_ID,
            memory_limit_mb=self.DOJO_MEMORY_LIMIT_MB,
            poll_seconds=self.DOJO_POLL_SECONDS,
            heartbeat_seconds=self.DOJO_HEARTBEAT_SECONDS,
            stale_seconds=self.DOJO_STALE_SECONDS,
        )
