"""Reconcile RADAR observations outside database transactions and row locks."""

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from off_key_core.config.logs import logger
from off_key_core.db.base import get_async_session_local
from off_key_core.db.collection import lock_collection_configuration
from off_key_core.db.models import MonitoringService, PipelineRun, PipelineRunEvent
from off_key_core.db.pipeline_locks import complete_stopped_runs, lock_execution_records
from off_key_core.db.run_events import RUN_EVENT_LIMIT, run_event
from off_key_core.schemas.radar import RadarOperationalStatus
from sqlalchemy import func, select, update
from sqlalchemy.exc import InterfaceError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .monitor_intent import (
    complete_stop,
    next_lifecycle_version,
    purge_service_rows,
    request_stop_values,
)
from .radar_lifecycle import RadarLifecycleController
from .radar_status import (
    TERMINAL_WORKLOAD_STATES,
    UNVERIFIED_WORKLOAD_STATES,
    apply_terminal_operational_status,
)
from .radar_workloads import RadarWorkloadManager
from .time_utils import coerce_utc

# Stages a terminal workload observation persists; seen again on the next pass,
# with no heartbeat in between, they mean the pool stopped restarting the worker.
ABANDONED_STAGES = frozenset({"failed", "stopped"})
# Stops wait for the pool to end a child, so a pass runs a few at once.
STOP_CONCURRENCY = 8


@dataclass(frozen=True, slots=True)
class _ServiceSnapshot:
    id: str
    container_id: str | None
    container_name: str
    desired_state: str
    lifecycle_version: int
    stop_requested_at: datetime | None
    config_fingerprint: str | None
    operational_updated_at: datetime | None
    operational_stage: str | None = None

    @classmethod
    def capture(cls, service: MonitoringService) -> "_ServiceSnapshot":
        return cls(
            service.id,
            service.container_id,
            service.container_name,
            getattr(service, "desired_state", "running"),
            getattr(service, "lifecycle_version", 1),
            service.stop_requested_at,
            getattr(service, "config_fingerprint", None),
            service.operational_updated_at,
            getattr(service, "operational_stage", None),
        )

    def matches(self, service: MonitoringService) -> bool:
        return (
            service.container_id == self.container_id
            and getattr(service, "lifecycle_version", 1) == self.lifecycle_version
            and getattr(service, "desired_state", "running") == self.desired_state
            and service.stop_requested_at == self.stop_requested_at
        )


class RadarStatusReconciliationService:
    """Snapshot, inspect with bounded concurrency, then apply short transitions."""

    def __init__(
        self,
        interval_seconds: int = 60,
        terminal_service_retention_hours: int = 24,
        *,
        workloads: RadarWorkloadManager | None = None,
    ) -> None:
        self.interval_seconds = interval_seconds
        self.terminal_service_retention_hours = terminal_service_retention_hours
        self.workloads = workloads if workloads is not None else RadarWorkloadManager()
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._reconcile()
            except asyncio.CancelledError:
                raise
            except SQLAlchemyError:
                logger.exception(
                    "RADAR reconciliation will retry after infrastructure failure"
                )
            except Exception:
                logger.exception("RADAR reconciliation failed")
            try:
                await asyncio.wait_for(self._stop_event.wait(), self.interval_seconds)
            except TimeoutError:
                continue

    async def _reconcile(self) -> None:
        async with get_async_session_local()() as session:
            await lock_collection_configuration(session)
            failed_ids = select(PipelineRun.service_id).where(
                PipelineRun.status == "failed"
            )
            await session.execute(
                update(MonitoringService)
                .where(
                    MonitoringService.id.in_(failed_ids),
                    MonitoringService.desired_state == "running",
                    MonitoringService.stop_requested_at.is_(None),
                )
                .values(**request_stop_values())
            )
            await session.commit()
            lifecycle = RadarLifecycleController(session, self.workloads)
            await lifecycle.remove_orphans()
            await lifecycle.recover_pending()
            await self._reconcile_with_session(session)

    async def _reconcile_with_session(self, session: AsyncSession) -> None:
        result = await session.execute(select(MonitoringService))
        snapshots = [
            _ServiceSnapshot.capture(service) for service in result.scalars().all()
        ]
        await session.commit()
        semaphore = asyncio.Semaphore(STOP_CONCURRENCY)
        statuses = dict(
            zip(
                [item.container_id for item in snapshots],
                [
                    state
                    for state, _ in await self.workloads.statuses_and_labels(
                        [item.container_id for item in snapshots]
                    )
                ],
                strict=True,
            )
        )

        async def inspect(snapshot):
            async with semaphore:
                return await self._inspect(snapshot, statuses)

        observations = await asyncio.gather(
            *(inspect(item) for item in snapshots), return_exceptions=True
        )
        for snapshot, observation in zip(snapshots, observations, strict=True):
            if isinstance(observation, BaseException):
                logger.warning(
                    "RADAR inspection deferred service_id=%s error=%s",
                    snapshot.id,
                    type(observation).__name__,
                )
                continue
            try:
                await self._apply_observation(session, snapshot, observation)
                await session.commit()
            except (OperationalError, InterfaceError):
                # A lost database connection fails every later row too; let the
                # loop back off and retry the whole pass.
                await session.rollback()
                raise
            except Exception:
                # One bad row must not hold back stops and purges for the rest.
                await session.rollback()
                logger.exception(
                    "RADAR reconciliation deferred service_id=%s", snapshot.id
                )
        await self._record_crashes(session, snapshots)

    async def _record_crashes(self, session, snapshots) -> None:
        """Record why a running pipeline's worker crashed, once per crash.

        A restarted worker heartbeats again, so without this a crash loop or an
        out-of-memory kill shows only as a gap in its status.
        """
        watched = [
            snapshot
            for snapshot in snapshots
            if snapshot.config_fingerprint
            and snapshot.container_id
            and snapshot.desired_state == "running"
            and snapshot.stop_requested_at is None
        ]

        found = await asyncio.gather(
            *(self.workloads.crashes(item.container_id) for item in watched),
            return_exceptions=True,
        )
        for snapshot, tasks in zip(watched, found, strict=True):
            if isinstance(tasks, BaseException) or not tasks:
                continue
            try:
                await self._record_service_crashes(session, snapshot.id, tasks)
                await session.commit()
            except (OperationalError, InterfaceError):
                await session.rollback()
                raise
            except Exception:
                await session.rollback()
                logger.exception(
                    "RADAR crash record deferred service_id=%s", snapshot.id
                )

    @staticmethod
    async def _record_service_crashes(session, service_id, tasks) -> None:
        run_id = await session.scalar(
            select(PipelineRun.id).where(PipelineRun.service_id == service_id)
        )
        if run_id is None:
            return
        recorded = await session.scalars(
            select(PipelineRunEvent.detail)
            .where(
                PipelineRunEvent.run_id == run_id,
                PipelineRunEvent.kind == "workload_crashed",
            )
            .order_by(PipelineRunEvent.id.desc())
            .limit(100)
        )
        known = {detail.get("task_id") for detail in recorded if detail}
        stored = await session.scalar(
            select(func.count(PipelineRunEvent.id)).where(
                PipelineRunEvent.run_id == run_id
            )
        )
        room = max(RUN_EVENT_LIMIT - (stored or 0), 0)
        # The pool keeps a few crashes of history; record the oldest new one first.
        for task in reversed(tasks[:10]):
            if task["task_id"] in known:
                continue
            if room == 0:
                break
            room -= 1
            session.add(run_event(run_id, "workload_crashed", detail=task))
            logger.warning(
                "event=tactic.radar_task_crashed service_id=%s run_id=%s "
                "task_id=%s state=%s exit_code=%s error=%s",
                service_id,
                run_id,
                task["task_id"],
                task["state"],
                task["exit_code"],
                task["error"],
            )

    async def _inspect(
        self, snapshot: _ServiceSnapshot, statuses: dict[str | None, str]
    ) -> str:
        if (
            snapshot.stop_requested_at is not None
            or snapshot.desired_state != "running"
        ):
            if snapshot.config_fingerprint:
                await self.workloads.remove_intent(snapshot.id, snapshot.container_id)
            else:
                await self._remove_workload_if_present(snapshot.container_id)
            return "stop_confirmed"
        if snapshot.config_fingerprint and snapshot.container_id is None:
            return "pending_creation"
        return statuses[snapshot.container_id]

    async def _apply_observation(
        self, session: AsyncSession, snapshot: _ServiceSnapshot, observation: str
    ) -> None:
        terminal = observation in TERMINAL_WORKLOAD_STATES
        if observation == "stop_confirmed" or (
            terminal and snapshot.config_fingerprint
        ):
            # A terminal managed worker may fail its run below; keep the
            # checkpoint, run, service lock order that worker fatal writes use.
            await lock_execution_records(session, [snapshot.id])
        service = await session.get(
            MonitoringService, snapshot.id, with_for_update=True, populate_existing=True
        )
        if service is None or not snapshot.matches(service):
            return
        if observation == "stop_confirmed":
            await self._apply_stopped(session, service)
        elif observation == "running":
            if not service.status:
                service.status = True
                self._mark_revived(service)
        elif terminal:
            # A heartbeat arriving after the workload snapshot is newer evidence.
            if service.operational_updated_at == snapshot.operational_updated_at:
                if self._is_abandoned(snapshot):
                    await self._fail_abandoned(session, service, observation)
                else:
                    self._apply_terminal(service, observation)
        elif observation in UNVERIFIED_WORKLOAD_STATES:
            logger.warning(
                "RADAR workload status unverifiable service_id=%s", service.id
            )

    @staticmethod
    def _is_abandoned(snapshot: _ServiceSnapshot) -> bool:
        """Whether the pool has given up on a managed worker that should run.

        The first terminal observation only records the workload state. When the
        next pass still finds the worker terminal, with no heartbeat in between,
        the pool is not restarting it: its restart attempts are spent, it exited
        cleanly, or its row is gone. Without this the row would keep its
        readings and capacity forever.
        """
        return bool(
            snapshot.config_fingerprint
            and snapshot.desired_state == "running"
            and snapshot.stop_requested_at is None
            and (snapshot.operational_stage or "").strip().lower() in ABANDONED_STAGES
        )

    async def _fail_abandoned(
        self, session: AsyncSession, service: MonitoringService, observation: str
    ) -> None:
        """End the run as failed and request the stop that releases its claim."""
        now = datetime.now(UTC)
        error = (
            f"The worker stopped and is not being restarted (workload: {observation}). "
            "Start the monitor again once the cause is fixed."
        )
        apply_terminal_operational_status(service, observation)
        run = await session.scalar(
            select(PipelineRun).where(PipelineRun.service_id == service.id)
        )
        if run is not None and run.ended_at is None and run.status != "failed":
            run.status = "failed"
            run.error = error
            run.ended_at = now
            run.final_status = run.final_status or service.operational_status
            session.add(
                run_event(
                    run.id,
                    "run_failed",
                    stage="failed",
                    occurred_at=now,
                    detail={"error": error, "workload_status": observation},
                )
            )
        service.desired_state = "stopped"
        service.stop_requested_at = now
        service.lifecycle_version = next_lifecycle_version(service)
        logger.warning(
            "event=tactic.radar_worker_abandoned service_id=%s workload_status=%s",
            service.id,
            observation,
        )

    async def _apply_stopped(
        self, session: AsyncSession, service: MonitoringService
    ) -> None:
        if getattr(service, "desired_state", None) == "deleted":
            await purge_service_rows(session, [service.id])
        elif service.stop_requested_at is not None or service.status:
            complete_stop(service)
            await complete_stopped_runs(session, [service.id])
        elif self._is_purge_due(service):
            await purge_service_rows(session, [service.id])

    def _apply_terminal(self, service: MonitoringService, workload_status: str) -> None:
        # Only rows that want to run reach here: every other row is inspected
        # as a stop. Desired intent owns the claim, including legacy rows whose
        # derived status was cleared by an older controller.
        service.status = True
        apply_terminal_operational_status(service, workload_status)

    def _is_purge_due(self, service: MonitoringService) -> bool:
        if service.status:
            return False
        reference_time = coerce_utc(
            service.operational_updated_at or service.created_at
        )
        if reference_time is None:
            return self.terminal_service_retention_hours == 0
        return reference_time <= datetime.now(UTC) - timedelta(
            hours=self.terminal_service_retention_hours
        )

    async def _remove_workload_if_present(self, container_id: str | None) -> bool:
        return await self.workloads.remove(container_id)

    @staticmethod
    def _mark_revived(service: MonitoringService) -> None:
        raw = service.operational_status or {}
        stage = (raw.get("stage") or service.operational_stage or "").strip().lower()
        if stage in {"failed", "stopped"}:
            service.operational_stage = "starting"
            service.operational_status = RadarOperationalStatus(
                stage="starting",
                detail="Runtime heartbeat has not arrived",
                is_stale=True,
            ).model_dump(mode="json", exclude_none=True)
            service.operational_updated_at = None
