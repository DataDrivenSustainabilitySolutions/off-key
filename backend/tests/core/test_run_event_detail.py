"""Run event details stay JSON-safe and inside their size budget."""

import json
import math
from datetime import UTC, datetime

from aberration_core.db.run_events import (
    MAX_DETAIL_BYTES,
    MAX_ITEMS,
    MAX_TEXT_LENGTH,
    bounded_detail,
    run_event,
    run_event_parameters,
)


def test_clips_text_lists_depth_and_non_finite_numbers():
    detail = bounded_detail(
        {
            "error": "x" * (MAX_TEXT_LENGTH + 10),
            "samples": list(range(MAX_ITEMS + 5)),
            "score": math.nan,
            "at": datetime(2026, 11, 3, tzinfo=UTC),
            "nested": {"a": {"b": {"c": {"d": "too deep"}}}},
            "other": object,
        }
    )
    assert detail["error"] == "x" * MAX_TEXT_LENGTH + "…"
    assert detail["samples"] == list(range(MAX_ITEMS))
    assert detail["score"] is None
    assert detail["at"] == "2026-11-03T00:00:00+00:00"
    assert detail["nested"] == {"a": {"b": {"c": None}}}
    assert detail["other"].startswith("<class")
    json.dumps(detail, allow_nan=False)


def test_oversized_details_keep_their_scalar_facts():
    bulky = {f"node-{index}": {"error": "e" * 900} for index in range(20)}
    detail = bounded_detail({"error": "Detector failed", "nodes": bulky})
    assert detail == {"error": "Detector failed", "truncated": True}
    wide = bounded_detail({f"key-{index}": "v" * 900 for index in range(40)})
    assert wide == {"truncated": True}
    assert len(json.dumps(bounded_detail({"nodes": bulky}))) <= MAX_DETAIL_BYTES


def test_writers_receive_bounded_rows():
    parameters = run_event_parameters(
        run_id="run-1",
        service_id="svc-1",
        kind="stage_changed",
        source="radar",
        stage="operational",
        detail={"threshold": math.inf},
    )
    assert json.loads(parameters["detail"]) == {"threshold": None}
    assert parameters["occurred_at"].tzinfo is UTC
    assert parameters["limit"] > 0
    row = run_event("run-1", "activation_phase", stage="requested")
    assert (row.source, row.detail) == ("tactic", {})
