"""Turn consecutive operational snapshots into a run's lifecycle events.

Heartbeats overwrite the service's status; these events keep the story: when
the worker started, each stage it entered and how long the previous one took,
why it degraded, and when its input stream lost messages. Events wait here
until a heartbeat persists them, so a brief database outage loses none.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Stages whose detail is the reason; a changed reason is a new event.
_REASONED_STAGES = frozenset({"degraded", "failed"})
MAX_PENDING_EVENTS = 100
COVERAGE_EVENT_INTERVAL_SECONDS = 3600.0
MAX_FAILED_NODES = 10


def _learning_summary(detector_stats: dict[str, Any]) -> dict[str, Any]:
    """The facts about training and calibration worth keeping on a transition."""
    summary: dict[str, Any] = {}
    for key in (
        "strategy",
        "threshold",
        "training_window_size",
        "calibration_window_size",
        "warmup_count",
        "calibration_count",
        "training_error",
    ):
        if detector_stats.get(key) is not None:
            summary[key] = detector_stats[key]
    pipeline_state = detector_stats.get("pipeline_state")
    if isinstance(pipeline_state, dict):
        for key in ("batch_training", "adaptive_learning", "preparation"):
            if isinstance(pipeline_state.get(key), dict):
                summary[key] = pipeline_state[key]
        nodes = pipeline_state.get("nodes")
        if isinstance(nodes, dict):
            failing = {
                node_id: {
                    "state": node.get("state"),
                    "error": node.get("error"),
                    "rejections": node.get("rejections") or {},
                }
                for node_id, node in sorted(nodes.items())
                if isinstance(node, dict)
                and (node.get("error") or node.get("state") == "failed")
            }
            if failing:
                summary["failing_nodes"] = dict(
                    list(failing.items())[:MAX_FAILED_NODES]
                )
    return summary


class RunEventRecorder:
    """Owned by the health monitor; holds events until a heartbeat stores them."""

    def __init__(
        self,
        *,
        coverage_interval_seconds: float = COVERAGE_EVENT_INTERVAL_SECONDS,
        max_pending: int = MAX_PENDING_EVENTS,
        clock=time.monotonic,
    ) -> None:
        self._pending: deque[dict[str, Any]] = deque()
        self._max_pending = max_pending
        self._dropped = 0
        self._clock = clock
        self._coverage_interval = coverage_interval_seconds
        self._started = False
        self._stage: str | None = None
        self._reason: str | None = None
        self._stage_since: float | None = None
        self._losses = 0
        self._coverage_event_at: float | None = None

    def record(
        self,
        kind: str,
        *,
        stage: str | None = None,
        detail: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> None:
        event_detail = dict(detail or {})
        if len(self._pending) >= self._max_pending:
            # Keep the newest events; the oldest are least useful in an outage.
            self._pending.popleft()
            self._dropped += 1
            event_detail["events_dropped"] = self._dropped
        self._pending.append(
            {
                "kind": kind,
                "stage": stage,
                "detail": event_detail,
                "occurred_at": occurred_at or datetime.now(UTC),
            }
        )

    def observe(
        self,
        status: dict[str, Any] | None,
        detector_stats: dict[str, Any] | None = None,
        *,
        started_at: datetime | None = None,
    ) -> None:
        """Compare one operational status with the previous one."""
        if not isinstance(status, dict):
            return
        detector_stats = detector_stats or {}
        stage = status.get("stage")
        detail = status.get("detail")
        now = self._clock()
        if not self._started:
            self._started = True
            recovery = status.get("recovery") or {}
            self.record(
                "runtime_started",
                stage=stage,
                occurred_at=started_at,
                detail={
                    "restored_from_checkpoint": bool(recovery.get("restored")),
                    "restored_processed_count": recovery.get(
                        "restored_processed_count"
                    ),
                    "restored_saved_at": recovery.get("restored_saved_at"),
                },
            )
            logger.info(
                "event=radar.runtime_started stage=%s restored=%s",
                stage,
                bool(recovery.get("restored")),
            )
            # Losses a restored checkpoint carries are history, not news.
            self._losses = self._loss_count(status.get("coverage"))
        reason = detail if stage in _REASONED_STAGES else None
        if stage != self._stage or reason != self._reason:
            previous_seconds = (
                round(now - self._stage_since, 1)
                if self._stage_since is not None and stage != self._stage
                else None
            )
            event_detail: dict[str, Any] = {
                "from": self._stage,
                "detail": detail,
                "previous_stage_seconds": previous_seconds,
                "processed_message_count": status.get("processed_message_count"),
                "progress": status.get("progress"),
                "error": status.get("error"),
            }
            event_detail.update(_learning_summary(detector_stats))
            self.record(
                "stage_changed",
                stage=stage,
                detail={k: v for k, v in event_detail.items() if v is not None},
            )
            log = logger.warning if stage in _REASONED_STAGES else logger.info
            log(
                "event=radar.stage_changed from=%s to=%s "
                "previous_stage_seconds=%s detail=%s",
                self._stage,
                stage,
                previous_seconds,
                detail,
            )
            if stage != self._stage:
                self._stage_since = now
            self._stage = stage
            self._reason = reason
        self._observe_coverage(status.get("coverage"), now)

    def _observe_coverage(self, coverage: Any, now: float) -> None:
        if not isinstance(coverage, dict):
            return
        losses = self._loss_count(coverage)
        if losses <= self._losses:
            return
        if (
            self._coverage_event_at is not None
            and now - self._coverage_event_at < self._coverage_interval
        ):
            return
        self.record(
            "coverage_gap",
            stage=self._stage,
            detail={
                "new_losses": losses - self._losses,
                "dropped_message_count": coverage.get("dropped_message_count"),
                "possible_gap_count": coverage.get("possible_gap_count"),
                "dropped_by_reason": coverage.get("dropped_by_reason") or {},
                "last_gap_reason": coverage.get("last_gap_reason"),
            },
        )
        logger.warning(
            "event=radar.coverage_gap new_losses=%s last_gap_reason=%s",
            losses - self._losses,
            coverage.get("last_gap_reason"),
        )
        self._losses = losses
        self._coverage_event_at = now

    @staticmethod
    def _loss_count(coverage: Any) -> int:
        if not isinstance(coverage, dict):
            return 0
        return int(coverage.get("dropped_message_count") or 0) + int(
            coverage.get("possible_gap_count") or 0
        )

    def pending(self) -> list[dict[str, Any]]:
        """Detached copies of the events waiting for persistence, oldest first."""
        return [dict(event) for event in self._pending]

    def acknowledge(self, count: int) -> None:
        """Forget the oldest ``count`` events once a heartbeat stored them."""
        for _ in range(min(count, len(self._pending))):
            self._pending.popleft()

    def drain(self) -> list[dict[str, Any]]:
        """Hand every waiting event to a final writer."""
        events = self.pending()
        self._pending.clear()
        return events
