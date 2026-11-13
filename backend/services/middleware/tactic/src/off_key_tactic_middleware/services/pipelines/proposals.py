"""Proposals: designs handed to a member to decide on, with the reason for them."""

from datetime import UTC, datetime
from uuid import uuid4

from off_key_core.config.logs import log_security_event
from off_key_core.db.models import Agent, PipelineProposal, User
from off_key_core.models.pipelines import validate_pipeline
from off_key_core.schemas.pipelines import (
    MAX_OPEN_PROPOSALS,
    MAX_PROPOSALS_LISTED,
    PipelineProposalCreate,
    PipelineProposalDecision,
    PipelineProposalList,
    PipelineProposalSummary,
    PipelineProposalView,
    ProposalStatus,
)
from sqlalchemy import func, select

from ...domain import ConflictError, ForbiddenError, NotFoundError, ValidationError
from .library import begin_library_write


def _fields(row: PipelineProposal, model) -> dict:
    return {key: getattr(row, key) for key in model.model_fields}


def proposal_view(row: PipelineProposal) -> PipelineProposalView:
    return PipelineProposalView.model_validate(_fields(row, PipelineProposalView))


def _wrote(row: PipelineProposal, caller: User | Agent) -> bool:
    if isinstance(caller, Agent):
        return row.author_kind == "agent" and row.agent_id == caller.id
    return row.author_kind == "member" and row.author == caller.email


class PipelineProposals:
    def __init__(self, session):
        self.session = session

    async def list(self, status: ProposalStatus | None = None) -> PipelineProposalList:
        statement = select(PipelineProposal).order_by(
            PipelineProposal.created_at.desc(), PipelineProposal.id
        )
        if status is not None:
            statement = statement.where(PipelineProposal.status == status)
        rows = await self.session.scalars(statement.limit(MAX_PROPOSALS_LISTED))
        return PipelineProposalList(
            items=[
                PipelineProposalSummary.model_validate(
                    _fields(row, PipelineProposalSummary)
                )
                for row in rows
            ]
        )

    async def get(self, identifier: str) -> PipelineProposalView:
        return proposal_view(await self._row(identifier))

    async def create(
        self, change: PipelineProposalCreate, caller: User | Agent
    ) -> PipelineProposalView:
        # The write lock makes the count hold until the commit.
        await begin_library_write(self.session)
        validation = validate_pipeline(change.definition)
        errors = [item for item in validation.issues if item.severity == "error"]
        if errors:
            raise ValidationError(
                "Propose a design without errors. "
                + " ".join(item.message for item in errors[:3])
            )
        slots = {slot.id for slot in change.definition.input_slots}
        unknown = sorted(set(change.bindings) - slots)
        if unknown:
            raise ValidationError(
                f"The design has no input named {unknown[0]}. "
                "Bind readings to its input slots by their id."
            )
        waiting = await self.session.scalar(
            select(func.count())
            .select_from(PipelineProposal)
            .where(PipelineProposal.status == "open")
        )
        if (waiting or 0) >= MAX_OPEN_PROPOSALS:
            raise ConflictError(
                f"{MAX_OPEN_PROPOSALS} proposals wait for a decision. "
                "A member decides some before another can be made."
            )
        agent = isinstance(caller, Agent)
        row = PipelineProposal(
            id=str(uuid4()),
            name=change.name,
            reason=change.reason,
            definition=change.definition.model_dump(mode="json"),
            layout=change.layout.model_dump(mode="json"),
            bindings=dict(change.bindings),
            test_run_id=change.test_run_id,
            replace_service_id=change.replace_service_id,
            author=caller.name if agent else caller.email,
            author_kind="agent" if agent else "member",
            agent_id=caller.id if agent else None,
            status="open",
            created_at=datetime.now(UTC),
        )
        self.session.add(row)
        await self.session.commit()
        return proposal_view(row)

    async def decide(
        self, identifier: str, decision: PipelineProposalDecision, member: User
    ) -> PipelineProposalView:
        row = await self._open(identifier)
        row.status = decision.status
        row.decided_by = member.email
        row.decided_at = datetime.now(UTC)
        row.decision_note = (decision.note or "").strip() or None
        await self.session.commit()
        log_security_event(
            "pipeline_proposal_decided",
            member.email,
            {"proposal_id": row.id, "status": row.status, "author": row.author},
        )
        return proposal_view(row)

    async def withdraw(
        self, identifier: str, caller: User | Agent
    ) -> PipelineProposalView:
        row = await self._open(identifier)
        if not _wrote(row, caller):
            raise ForbiddenError("Only its author can withdraw a proposal")
        row.status = "withdrawn"
        row.decided_at = datetime.now(UTC)
        await self.session.commit()
        return proposal_view(row)

    async def _row(self, identifier: str, *, lock: bool = False) -> PipelineProposal:
        statement = select(PipelineProposal).where(PipelineProposal.id == identifier)
        row = await self.session.scalar(
            statement.with_for_update() if lock else statement
        )
        if row is None:
            raise NotFoundError("Proposal not found")
        return row

    async def _open(self, identifier: str) -> PipelineProposal:
        """The proposal, locked, while it still waits for a decision."""
        row = await self._row(identifier, lock=True)
        if row.status != "open":
            raise ConflictError(f"This proposal is already {row.status}")
        return row
