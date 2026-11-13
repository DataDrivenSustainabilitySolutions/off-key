"""Record, inspect and stop RADAR workloads that the RADAR pool runs.

A workload is a row of ``radar_workloads``. Creating one asks the pool to run
it; a pool replica claims it with a lease and runs it as a child process. No
TACTIC or API process reaches Docker. Each call here runs in a short
transaction of its own, so it never holds a caller's transaction open while it
waits for the pool.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from off_key_core.db.base import get_async_session_local
from off_key_core.db.workloads import WORKLOAD_DONE, RadarWorkload
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from ...config.config import get_tactic_settings
from .radar_environment import build_radar_workload_labels
from .workload_identity import (
    has_labels,
    radar_identity_labels,
    radar_workload_name,
    workload_labels,
)

# The observable states of a workload, as status projection reads them. Besides
# the row states: "no_container_id" (nothing recorded), "not_found" (row gone).
RUNNING = "running"
MONITOR_MODULE = "off_key_mqtt_radar"
PREFLIGHT_MODULE = "off_key_mqtt_radar.preflight"


@dataclass(frozen=True)
class Workload:
    """What callers need of a workload row."""

    id: str
    name: str
    kind: str
    runtime: str
    labels: dict[str, str] = field(default_factory=dict)
    environment: dict[str, str] = field(default_factory=dict)
    state: str = "pending"
    exit_code: int | None = None
    detail: str | None = None
    output: str | None = None
    crashes: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def of(cls, row: RadarWorkload) -> "Workload":
        return cls(
            id=row.id,
            name=row.name,
            kind=row.kind,
            runtime=row.runtime,
            labels=dict(row.labels or {}),
            environment=dict(row.environment or {}),
            state=observed_state(row),
            exit_code=row.exit_code,
            detail=row.detail,
            output=row.output,
            crashes=list(row.crashes or []),
        )


def observed_state(row: RadarWorkload) -> str:
    """A running row whose lease lapsed waits for another worker: pending."""
    if row.state == RUNNING and (
        row.lease_expires_at is None or row.lease_expires_at < datetime.now(UTC)
    ):
        return "pending"
    return row.state


class RadarWorkloadManager:
    """Create, inspect, and remove RADAR workloads in the pool's table."""

    def __init__(self, sessions=None):
        self._sessions = sessions

    @property
    def sessions(self):
        return self._sessions or get_async_session_local()

    async def _row(self, session, *, name=None, workload_id=None):
        query = select(RadarWorkload)
        if name is not None:
            query = query.where(RadarWorkload.name == name)
        else:
            query = query.where(RadarWorkload.id == workload_id)
        return await session.scalar(query.execution_options(populate_existing=True))

    async def find_named(self, name: str) -> Workload | None:
        async with self.sessions() as session:
            row = await self._row(session, name=name)
            return None if row is None else Workload.of(row)

    async def get(self, workload_id: str | None) -> Workload | None:
        if not workload_id:
            return None
        async with self.sessions() as session:
            row = await self._row(session, workload_id=workload_id)
            return None if row is None else Workload.of(row)

    async def find(self, service_id: str) -> Workload | None:
        """The monitor's workload, including one an interrupted request made."""
        return await self.find_named(radar_workload_name(service_id))

    async def ensure(self, service_id: str, environment: dict[str, str]) -> Workload:
        """Idempotently create or adopt one workload for a persisted generation."""
        workload = await self.find(service_id)
        if workload is None:
            workload = await self.create(service_id, environment)
        if not has_labels(workload, radar_identity_labels(service_id, environment)):
            raise RuntimeError(
                "Existing RADAR workload does not match its persisted intent"
            )
        return workload

    async def create(self, service_id: str, environment: dict[str, str]) -> Workload:
        config = get_tactic_settings().config
        runtime = environment.get("RADAR_RUNTIME_IMAGE", config.radar_image)
        return await self.submit(
            name=radar_workload_name(service_id),
            kind="monitor",
            module=MONITOR_MODULE,
            runtime=runtime,
            environment=environment,
            labels=build_radar_workload_labels(environment, runtime),
            restart=config.pool.restart_monitors,
        )

    async def submit(
        self,
        *,
        name: str,
        kind: str,
        module: str,
        runtime: str,
        environment: dict[str, str],
        labels: dict[str, str],
        restart: bool,
    ) -> Workload:
        """Record one workload for the pool, or return the one already named."""
        budget = get_tactic_settings().config.pool
        async with self.sessions() as session:
            session.add(
                RadarWorkload(
                    id=uuid.uuid4().hex,
                    name=name,
                    kind=kind,
                    module=module,
                    runtime=runtime,
                    environment=environment,
                    labels=labels,
                    memory_limit_bytes=budget.memory_limit_bytes,
                    restart=restart,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                # Another controller or a previously timed-out request won.
                await session.rollback()
            row = await self._row(session, name=name)
            if row is None:
                raise RuntimeError(f"RADAR workload {name} vanished after creation")
            return Workload.of(row)

    async def validate_started(self, workload: Workload) -> None:
        """Fail when a new workload ends before it could run.

        A workload no replica has claimed yet is not a failure: it starts as
        soon as the pool has room.
        """
        grace_seconds = get_tactic_settings().config.radar_startup_grace_seconds
        if grace_seconds > 0:
            await asyncio.sleep(grace_seconds)
        current = await self.get(workload.id)
        if current is None:
            raise RuntimeError(
                f"RADAR workload {workload.id} disappeared during startup"
            )
        if current.state in WORKLOAD_DONE:
            detail = current.detail or f"exit code {current.exit_code}"
            raise RuntimeError(
                f"RADAR workload {workload.id} failed during startup "
                f"(state={current.state}): {detail}"
            )

    async def remove_intent(self, service_id: str, workload_id: str | None) -> bool:
        """Remove an attached workload and any unknown outcome at its name."""
        removed = await self.remove(workload_id)
        workload = await self.find(service_id)
        if workload is not None:
            if workload_labels(workload).get("radar_service_id") != service_id:
                raise RuntimeError(
                    "Refusing to remove a RADAR workload with a different owner"
                )
            removed = await self.remove(workload.id) or removed
        return removed

    async def request_stop(self, workload_id: str) -> None:
        async with self.sessions() as session:
            await session.execute(
                update(RadarWorkload)
                .where(RadarWorkload.id == workload_id)
                .values(desired="stop")
            )
            await session.commit()

    async def remove(self, workload_id: str | None) -> bool:
        """Stop a workload and delete its row once no child runs it.

        The monitor's sensor claim is released only after this returns, so it
        waits for the pool to confirm the child ended, or for its lease to lapse.
        """
        if not workload_id:
            return False
        if await self.get(workload_id) is None:
            return False
        await self.request_stop(workload_id)
        await self.wait_stopped(workload_id)
        async with self.sessions() as session:
            await session.execute(
                delete(RadarWorkload).where(RadarWorkload.id == workload_id)
            )
            await session.commit()
        return True

    async def wait_stopped(self, workload_id: str) -> None:
        try:
            async with asyncio.timeout(
                get_tactic_settings().config.radar_stop_timeout_seconds
            ):
                while True:
                    current = await self.get(workload_id)
                    if current is None or current.state != RUNNING:
                        return
                    await asyncio.sleep(0.2)
        except TimeoutError:
            raise RuntimeError(
                "RADAR workload has not stopped; the sensor claim is retained"
            ) from None

    async def list_managed(self) -> list[Workload]:
        """Every monitor workload of this deployment."""
        async with self.sessions() as session:
            rows = (
                await session.scalars(
                    select(RadarWorkload).where(RadarWorkload.kind == "monitor")
                )
            ).all()
            return [Workload.of(row) for row in rows]

    async def list_managed_ids(self) -> set[str]:
        return {workload.id for workload in await self.list_managed()}

    async def get_status_and_labels(
        self, workload_id: str | None
    ) -> tuple[str, dict[str, str]]:
        """The workload's observed state and labels.

        States: a row state, "no_container_id" or "not_found".
        """
        return (await self.statuses_and_labels([workload_id]))[0]

    async def statuses_and_labels(
        self, workload_ids: list[str | None]
    ) -> list[tuple[str, dict[str, str]]]:
        """The observed state and labels of each workload, in one read."""
        wanted = {workload_id for workload_id in workload_ids if workload_id}
        found: dict[str, Workload] = {}
        if wanted:
            async with self.sessions() as session:
                rows = await session.scalars(
                    select(RadarWorkload).where(RadarWorkload.id.in_(wanted))
                )
                found = {row.id: Workload.of(row) for row in rows}
        result: list[tuple[str, dict[str, str]]] = []
        for workload_id in workload_ids:
            if not workload_id:
                result.append(("no_container_id", {}))
            elif (workload := found.get(workload_id)) is None:
                result.append(("not_found", {}))
            else:
                result.append((workload.state, workload.labels))
        return result

    async def crashes(self, workload_id: str | None) -> list[dict[str, Any]]:
        """Why the workload's children crashed, newest first."""
        workload = await self.get(workload_id)
        return [] if workload is None else workload.crashes
