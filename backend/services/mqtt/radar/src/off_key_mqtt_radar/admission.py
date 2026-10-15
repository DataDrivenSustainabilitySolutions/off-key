"""Fence a delayed managed Docker creation against durable controller intent."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import text


class RadarAdmissionSettings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=True, extra="ignore")

    SERVICE_ID: str = "default"
    # Absent for standalone and already-running pre-lifecycle workers.
    RADAR_LIFECYCLE_VERSION: int | None = Field(default=None, ge=1)


async def require_monitor_admission(*, settings=None, session_factory=None) -> None:
    """Fail closed before a managed worker starts its detector or subscribes."""
    settings = settings or RadarAdmissionSettings()
    if settings.RADAR_LIFECYCLE_VERSION is None:
        return
    if session_factory is None:
        from .database import get_radar_async_session_factory

        session_factory = get_radar_async_session_factory()
    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT desired_state, lifecycle_version, stop_requested_at "
                    "FROM services WHERE id = :service_id"
                ),
                {"service_id": settings.SERVICE_ID},
            )
        ).first()
    if (
        row is None
        or row.desired_state != "running"
        or row.lifecycle_version != settings.RADAR_LIFECYCLE_VERSION
        or row.stop_requested_at is not None
    ):
        raise RuntimeError("RADAR workload no longer owns a running monitor intent")
