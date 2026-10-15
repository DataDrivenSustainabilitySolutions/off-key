"""Account for monitoring gaps independently of log suppression and reconnects."""

from datetime import UTC, datetime
from threading import Lock
from typing import Any

from off_key_core.schemas.radar import RadarCoverageStatus


class CoverageTracker:
    """Keep monitor-lifetime loss counters safe for Paho's network thread.

    A gap remains visible after traffic resumes. Receiving new data cannot repair
    a discarded observation or establish what was missed during a disconnect.
    """

    def __init__(self, state: dict[str, Any] | None = None):
        self._lock = Lock()
        self._state = RadarCoverageStatus.model_validate(state or {})

    def restore(self, state: dict[str, Any]) -> None:
        """Restore a validated checkpoint before ingestion starts."""
        restored = RadarCoverageStatus.model_validate(state)
        with self._lock:
            self._state = restored

    def record_received(self) -> None:
        with self._lock:
            self._state.received_message_count += 1

    def record_drop(self, reason: str, count: int = 1) -> None:
        """Count observations known to have been discarded locally."""
        if count < 1:
            raise ValueError("Dropped observation count must be positive")
        with self._lock:
            self._state.dropped_message_count += count
            self._state.dropped_by_reason[reason] = (
                self._state.dropped_by_reason.get(reason, 0) + count
            )
            self._record_gap(reason)

    def record_possible_gap(self, reason: str) -> None:
        """Record an interruption whose missing observation count is unknown."""
        with self._lock:
            self._state.possible_gap_count += 1
            self._record_gap(reason)

    def _record_gap(self, reason: str) -> None:
        self._state.has_gaps = True
        self._state.last_gap_at = datetime.now(UTC)
        self._state.last_gap_reason = reason

    def snapshot(self) -> RadarCoverageStatus:
        with self._lock:
            return self._state.model_copy(deep=True)
