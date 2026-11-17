"""Who started and stopped each monitor, and why.

Every start and stop adds a record, so a monitor's history says why it
changed. The first start names who the monitor belongs to: a key may stop only
the shadow monitors it started itself.
"""

from collections import defaultdict

from off_key_core.db.models import Agent, MonitorEventRecord, PipelineProposal, User
from off_key_core.schemas.pipelines import (
    MonitorEvent,
    MonitorOrigin,
    MonitorRationale,
    MonitorRecord,
)
from sqlalchemy import select

# A monitor's history is short; this keeps a misbehaving caller from growing it.
MAX_RECORDS_SHOWN = 50


def record(
    session,
    service_id: str,
    event: MonitorEvent,
    caller: User | Agent,
    *,
    rationale: MonitorRationale | None = None,
    note: str | None = None,
    test_run_id: str | None = None,
    shadow: bool = False,
    proposal: PipelineProposal | None = None,
) -> MonitorEventRecord:
    """Add a step to a monitor's history; the caller commits it.

    A start that accepts a ``proposal`` names its author, who designed the
    monitor, and notes the member who started it.
    """
    agent = isinstance(caller, Agent)
    who = caller.name if agent else caller.email
    if proposal is not None:
        author, author_kind, agent_id = (
            proposal.author,
            proposal.author_kind,
            proposal.agent_id,
        )
        note = note or f"Proposed by {proposal.author}, started by {who}."
    else:
        author = who
        author_kind = "agent" if agent else "member"
        agent_id = caller.id if agent else None
    row = MonitorEventRecord(
        service_id=service_id,
        event=event,
        author=author,
        author_kind=author_kind,
        agent_id=agent_id,
        rationale=rationale.model_dump(mode="json") if rationale else None,
        note=note,
        test_run_id=test_run_id,
        shadow=shadow,
    )
    session.add(row)
    return row


def _record_view(row: MonitorEventRecord) -> MonitorRecord:
    return MonitorRecord.model_validate(
        {
            "event": row.event,
            "author": row.author,
            "author_kind": row.author_kind,
            "rationale": row.rationale,
            "note": row.note,
            "test_run_id": row.test_run_id,
            "shadow": row.shadow,
            "at": row.created_at,
        }
    )


def _origin(rows: list[MonitorEventRecord]) -> MonitorOrigin | None:
    started = [row for row in rows if row.event == "started"]
    if not started:
        return None
    first, latest = started[0], started[-1]
    return MonitorOrigin.model_validate(
        {
            "author": first.author,
            "author_kind": first.author_kind,
            "rationale": latest.rationale,
            "test_run_id": latest.test_run_id,
            "history": [_record_view(row) for row in rows[-MAX_RECORDS_SHOWN:]],
        }
    )


async def origins(session, service_ids: list[str]) -> dict[str, MonitorOrigin]:
    """The origin of each monitor that has one, by its id."""
    if not service_ids:
        return {}
    rows = await session.scalars(
        select(MonitorEventRecord)
        .where(MonitorEventRecord.service_id.in_(service_ids))
        .order_by(MonitorEventRecord.service_id, MonitorEventRecord.id)
    )
    grouped: dict[str, list[MonitorEventRecord]] = defaultdict(list)
    for row in rows:
        grouped[row.service_id].append(row)
    found = {key: _origin(items) for key, items in grouped.items()}
    return {key: value for key, value in found.items() if value is not None}


async def starter(session, service_id: str) -> MonitorEventRecord | None:
    """The record of the first start, which names who the monitor belongs to."""
    return await session.scalar(
        select(MonitorEventRecord)
        .where(
            MonitorEventRecord.service_id == service_id,
            MonitorEventRecord.event == "started",
        )
        .order_by(MonitorEventRecord.id)
        .limit(1)
    )
