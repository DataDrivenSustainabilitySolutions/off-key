"""What an agent's key may delete in the Dojo: what it made, and no evidence.

A key tests designs and leaves datasets and runs behind. It may delete those,
but nothing a member or another key made, and no run that a member reads as
the reason a design was proposed or runs: the test of a proposal that waits or
was accepted, or of a started monitor.
"""

from collections.abc import Iterable

from off_key_core.db.models import Agent, MonitorEventRecord, PipelineProposal, User
from sqlalchemy import select

from ...domain import ConflictError

# A withdrawn or declined proposal no longer asks anything of its test.
PROPOSALS_KEEPING_THEIR_TEST = ("open", "accepted")


def made_by(caller: User | Agent, member_column, agent_column):
    """Where a row was made by the caller: a key's own, or the member's own."""
    if isinstance(caller, Agent):
        return agent_column == caller.id
    return member_column == caller.id


async def evidence_runs(session, run_ids: Iterable[str]) -> set[str]:
    """The runs a proposal or a monitor names as its test."""
    run_ids = list(run_ids)
    if not run_ids:
        return set()
    proposed = select(PipelineProposal.test_run_id).where(
        PipelineProposal.test_run_id.in_(run_ids),
        PipelineProposal.status.in_(PROPOSALS_KEEPING_THEIR_TEST),
    )
    started = select(MonitorEventRecord.test_run_id).where(
        MonitorEventRecord.test_run_id.in_(run_ids)
    )
    return set((await session.scalars(proposed.union(started))).all())


async def require_no_evidence(session, run_ids: Iterable[str]) -> None:
    """Refuse to delete a run a proposal or a monitor names as its test."""
    if await evidence_runs(session, run_ids):
        raise ConflictError(
            "A proposal that waits or was accepted, or a monitor, names this "
            "test as its evidence, so it stays. Withdraw a waiting proposal "
            "first; the test of an accepted one or of a monitor is kept."
        )
