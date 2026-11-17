"""Who started and stopped a monitor, and why, as members and agents read it."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from off_key_core.db.models import MonitorEventRecord
from off_key_core.schemas.pipelines import MonitorRationale
from off_key_tactic_middleware.domain import ForbiddenError, ValidationError
from off_key_tactic_middleware.services.orchestration.radar import (
    RadarOrchestrationService,
)
from off_key_tactic_middleware.services.pipelines import history
from pydantic import ValidationError as Invalid

from tests.support.gateway import agent, member

WHY = {
    "watches": "Pump vibration rising above its usual daily band.",
    "why": "A moving Mahalanobis distance on vibration and current.",
    "evidence": "1 alarm in 9 scored hours of the last week; no labels.",
    "limits": "First mornings alarm until it has seen a few days.",
}
THEN = datetime(2026, 3, 1, tzinfo=UTC)


def test_a_rationale_is_four_short_fields():
    assert MonitorRationale.model_validate(WHY).model_dump() == WHY
    # Spacing is the author's, not the reader's.
    spaced = MonitorRationale.model_validate(WHY | {"why": "  Two\n  lines. "})
    assert spaced.why == "Two lines."
    for field in WHY:
        with pytest.raises(Invalid, match=field):
            MonitorRationale.model_validate(WHY | {field: "x" * 201})
        with pytest.raises(Invalid, match=field):
            MonitorRationale.model_validate(WHY | {field: "   "})
        with pytest.raises(Invalid, match=field):
            MonitorRationale.model_validate(
                {k: v for k, v in WHY.items() if k != field}
            )


def recorded(event, caller, minutes, **fields) -> MonitorEventRecord:
    session = MagicMock()
    row = history.record(session, "s1", event, caller, **fields)
    row.created_at = THEN + timedelta(minutes=minutes)
    return row


def test_the_first_start_names_the_owner_and_the_latest_says_why():
    key = agent()
    retuned = WHY | {"evidence": "No alarm in a day of shadow."}
    rows = [
        recorded(
            "started",
            key,
            0,
            rationale=MonitorRationale.model_validate(WHY),
            test_run_id="t1",
            shadow=True,
        ),
        recorded("stopped", member(), 5, note="Paused for maintenance."),
        recorded(
            "started",
            member(),
            10,
            rationale=MonitorRationale.model_validate(retuned),
        ),
    ]
    origin = history._origin(rows)
    assert origin is not None
    assert (origin.author, origin.author_kind) == ("Designer", "agent")
    assert origin.rationale is not None and origin.rationale.evidence == (
        "No alarm in a day of shadow."
    )
    assert origin.test_run_id is None
    assert [item.event for item in origin.history] == ["started", "stopped", "started"]
    assert origin.history[0].shadow and origin.history[0].test_run_id == "t1"
    assert origin.history[1].note == "Paused for maintenance."
    assert origin.history[1].author_kind == "member"
    # A monitor that was only ever stopped here was started before records.
    assert history._origin(rows[1:2]) is None


def orchestration(started: MonitorEventRecord | None, monkeypatch):
    service = RadarOrchestrationService(AsyncMock())
    service.session.add = MagicMock()
    service.stop_radar_service = AsyncMock(return_value=True)
    monkeypatch.setattr(history, "starter", AsyncMock(return_value=started))
    return service


@pytest.mark.asyncio
async def test_a_key_stops_only_a_shadow_monitor_it_started(monkeypatch):
    key = agent(starts="shadow")
    other = agent(id=5, name="Other")
    in_shadow = recorded("started", key, 0, shadow=True)

    service = orchestration(in_shadow, monkeypatch)
    with pytest.raises(ValidationError, match="note"):
        await service.stop_monitor_as("s1", key)
    with pytest.raises(ForbiddenError, match="only the monitors it started"):
        await service.stop_monitor_as("s1", other, "Not mine.")
    service.stop_radar_service.assert_not_awaited()

    live = orchestration(recorded("started", key, 0, shadow=False), monkeypatch)
    with pytest.raises(ForbiddenError, match="runs live"):
        await live.stop_monitor_as("s1", key, "Too noisy.")
    unrecorded = orchestration(None, monkeypatch)
    with pytest.raises(ForbiddenError):
        await unrecorded.stop_monitor_as("s1", key, "Too noisy.")

    service = orchestration(in_shadow, monkeypatch)
    assert await service.stop_monitor_as("s1", key, "Too noisy.")
    service.stop_radar_service.assert_awaited_once_with("s1")
    [stopped] = [call.args[0] for call in service.session.add.call_args_list]
    assert (stopped.event, stopped.author, stopped.agent_id, stopped.note) == (
        "stopped",
        "Designer",
        key.id,
        "Too noisy.",
    )
    service.session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_member_stops_any_monitor_and_it_is_recorded(monkeypatch):
    service = orchestration(None, monkeypatch)
    assert await service.stop_monitor_as("s1", member())
    [stopped] = [call.args[0] for call in service.session.add.call_args_list]
    assert (stopped.event, stopped.author_kind, stopped.note) == (
        "stopped",
        "member",
        None,
    )
    service.stop_radar_service = AsyncMock(return_value=False)
    service.session.add.reset_mock()
    # Nothing stopped, nothing recorded.
    assert not await service.stop_monitor_as("s1", member())
    service.session.add.assert_not_called()
