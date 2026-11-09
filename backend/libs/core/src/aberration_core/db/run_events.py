"""Lifecycle events of a pipeline run, written by TACTIC and RADAR.

Events are a bounded, durable timeline: what a run went through and why it
stopped. They outlive the service row, which stop and retention purge delete.
Details are clipped so a noisy writer cannot grow one run without bound.
"""

import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import text

from .pipelines import PipelineRunEvent

RunEventSource = Literal["radar", "tactic"]

# Rows one run may hold; a flapping runtime stops adding events at this cap.
RUN_EVENT_LIMIT = 2000
MAX_DETAIL_BYTES = 8192
MAX_TEXT_LENGTH = 1000
MAX_ITEMS = 50
MAX_DEPTH = 4

# RADAR's writer: only the run its service owns, and only below the cap.
INSERT_RUN_EVENT = text("""
    INSERT INTO monitoring_pipeline_run_events
        (run_id, occurred_at, source, kind, stage, detail)
    SELECT run.id, CAST(:occurred_at AS timestamptz), :source, :kind, :stage,
        CAST(:detail AS jsonb)
    FROM monitoring_pipeline_runs AS run
    WHERE run.id = :run_id
        AND run.service_id = :service_id
        AND (
            SELECT count(*) FROM monitoring_pipeline_run_events
            WHERE run_id = :run_id
        ) < :limit
""")


def _clip(value: Any, depth: int = 0) -> Any:
    if isinstance(value, str):
        if len(value) > MAX_TEXT_LENGTH:
            return value[:MAX_TEXT_LENGTH] + "…"
        return value
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, datetime):
        return value.isoformat()
    if depth >= MAX_DEPTH:
        return None
    if isinstance(value, Mapping):
        items = list(value.items())[:MAX_ITEMS]
        return {str(key): _clip(item, depth + 1) for key, item in items}
    if isinstance(value, list | tuple | set | frozenset):
        return [_clip(item, depth + 1) for item in list(value)[:MAX_ITEMS]]
    return _clip(str(value), depth)


def bounded_detail(detail: Mapping[str, Any] | None) -> dict[str, Any]:
    """A JSON-safe copy of ``detail`` within the per-event size budget."""
    clipped = _clip(dict(detail or {}))
    if len(json.dumps(clipped, allow_nan=False)) <= MAX_DETAIL_BYTES:
        return clipped
    # Keep the scalar facts, which carry the meaning, and drop nested bulk.
    scalars = {
        key: value
        for key, value in clipped.items()
        if not isinstance(value, dict | list)
    }
    scalars["truncated"] = True
    if len(json.dumps(scalars, allow_nan=False)) <= MAX_DETAIL_BYTES:
        return scalars
    return {"truncated": True}


def run_event_parameters(
    *,
    run_id: str,
    service_id: str,
    kind: str,
    source: RunEventSource,
    stage: str | None = None,
    detail: Mapping[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    """Bind parameters for ``INSERT_RUN_EVENT``."""
    return {
        "run_id": run_id,
        "service_id": service_id,
        "source": source,
        "kind": kind,
        "stage": stage,
        "detail": json.dumps(bounded_detail(detail), allow_nan=False),
        "occurred_at": occurred_at or datetime.now(UTC),
        "limit": RUN_EVENT_LIMIT,
    }


def run_event(
    run_id: str,
    kind: str,
    *,
    stage: str | None = None,
    detail: Mapping[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> PipelineRunEvent:
    """A TACTIC event row; TACTIC's events are few and bounded by lifecycle."""
    return PipelineRunEvent(
        run_id=run_id,
        occurred_at=occurred_at or datetime.now(UTC),
        source="tactic",
        kind=kind,
        stage=stage,
        detail=bounded_detail(detail),
    )
