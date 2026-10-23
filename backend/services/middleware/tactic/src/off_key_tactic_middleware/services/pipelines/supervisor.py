"""Schedule independent durable activations without queuing their controller leases."""

import asyncio
from datetime import UTC, datetime

from off_key_core.config.logs import logger
from off_key_core.db.base import get_async_session_local
from off_key_core.db.models import PipelineActivation
from off_key_core.db.pipeline_claims import TERMINAL_ACTIVATION_PHASES
from sqlalchemy import or_, select

from ...config.config import get_tactic_settings
from .activation import PipelineActivations
from .preflight_cleanup import PreflightOrphans


class PipelineActivationSupervisor:
    def __init__(self, workloads, *, sessions=None):
        self.workloads = workloads
        self.sessions = sessions
        self.tasks: dict[str, asyncio.Task] = {}
        self.active: dict[str, set[str]] = {
            "preflight": set(),
            "transition": set(),
            "check": set(),
        }
        self.loops: list[asyncio.Task] = []

    def _session(self):
        return (self.sessions or get_async_session_local())()

    async def start(self):
        if not self.loops:
            self.loops = [
                asyncio.create_task(self._loop(), name="pipeline-activations"),
                asyncio.create_task(self._cleanup_loop(), name="pipeline-orphans"),
            ]

    async def stop(self):
        tasks = [*self.loops, *self.tasks.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.loops.clear()
        self.tasks.clear()
        for group in self.active.values():
            group.clear()

    async def reconcile(self):
        """Advance each eligible activation once, in its own session and task.

        Checks have their own capacity so remote transitions cannot starve them.
        Waiting for capacity holds neither a session nor a lease, and the next
        pass can admit a newly cancelled request immediately.
        """
        async with self._session() as session:
            pending = (
                await session.execute(
                    select(
                        PipelineActivation.id,
                        PipelineActivation.phase,
                        PipelineActivation.cancel_requested,
                    )
                    .where(
                        PipelineActivation.phase.not_in(TERMINAL_ACTIVATION_PHASES),
                        or_(
                            PipelineActivation.controller_token.is_(None),
                            PipelineActivation.lease_expires_at.is_(None),
                            PipelineActivation.lease_expires_at <= datetime.now(UTC),
                        ),
                    )
                    .order_by(PipelineActivation.updated_at, PipelineActivation.id)
                )
            ).all()
        config = get_tactic_settings().config
        limits = {
            "preflight": config.pipeline_max_concurrent_preflights,
            "transition": config.pipeline_max_concurrent_transitions,
            "check": config.pipeline_max_concurrent_transitions,
        }
        for row in pending:
            if row.id in self.tasks:
                continue
            if row.cancel_requested:
                group = "transition"
            elif row.phase in {"requested", "preflighting"}:
                group = "preflight"
            elif row.phase in {"awaiting_heartbeat", "validated"}:
                group = "check"
            else:
                group = "transition"
            if len(self.active[group]) >= limits[group]:
                continue
            self.active[group].add(row.id)
            self.tasks[row.id] = asyncio.create_task(
                self._advance(row.id, group), name=f"pipeline-activation-{row.id}"
            )

    async def _advance(self, identifier, group):
        try:
            async with self._session() as session:
                await PipelineActivations(session, self.workloads).advance(identifier)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Pipeline activation reconciliation deferred activation_id=%s",
                identifier,
            )
        finally:
            self.tasks.pop(identifier, None)
            self.active[group].discard(identifier)

    async def _loop(self):
        while True:
            try:
                await self.reconcile()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Pipeline activation scheduling deferred")
            await asyncio.sleep(1)

    async def _cleanup_loop(self):
        while True:
            try:
                async with self._session() as session:
                    await PreflightOrphans(session, self.workloads).sweep()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Pipeline preflight cleanup deferred")
            await asyncio.sleep(1)
