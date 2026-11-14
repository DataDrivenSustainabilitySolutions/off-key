"""Proposals: designs handed to a member to decide on, with the reason for them."""

from datetime import UTC, datetime
from uuid import uuid4

from off_key_core.config.logs import log_security_event
from off_key_core.db.collection_runtime import read_collection_runtime
from off_key_core.db.models import (
    Agent,
    DojoRun,
    DojoRunResult,
    PipelineProposal,
    User,
)
from off_key_core.db.pipeline_claims import monitors_holding_capacity
from off_key_core.models.pipelines import validate_pipeline
from off_key_core.schemas.pipelines import (
    MAX_OPEN_PROPOSALS,
    MAX_PROPOSALS_LISTED,
    MonitorCapacity,
    PipelineDefinition,
    PipelineProposalCreate,
    PipelineProposalDecision,
    PipelineProposalList,
    PipelineProposalSummary,
    PipelineProposalView,
    ProposalStatus,
)
from sqlalchemy import func, select

from ...config.config import get_tactic_settings
from ...domain import ConflictError, ForbiddenError, NotFoundError, ValidationError
from .library import begin_library_write


def _fields(row: PipelineProposal, model) -> dict:
    # missing_readings is read from the catalogue, not stored with the row.
    return {
        key: getattr(row, key)
        for key in model.model_fields
        if key != "missing_readings"
    }


def proposal_view(
    row: PipelineProposal, recorded: set[str] | None = None
) -> PipelineProposalView:
    return PipelineProposalView.model_validate(
        _fields(row, PipelineProposalView)
        | {"missing_readings": _missing(row, recorded)}
    )


def _missing(row: PipelineProposal, recorded: set[str] | None) -> list[str]:
    """Bound readings gone from the catalogue; only an open proposal can still start."""
    if recorded is None or row.status != "open":
        return []
    return sorted(set((row.bindings or {}).values()) - recorded)


def _wrote(row: PipelineProposal, caller: User | Agent) -> bool:
    if isinstance(caller, Agent):
        return row.author_kind == "agent" and row.agent_id == caller.id
    return row.author_kind == "member" and row.author == caller.email


class PipelineProposals:
    def __init__(self, session):
        self.session = session

    async def _recorded(self) -> set[str] | None:
        """The readings a monitor can bind now; None when that is unknown."""
        try:
            # A savepoint keeps a failed read from ending the caller's transaction.
            async with self.session.begin_nested():
                snapshot = await read_collection_runtime(self.session)
            return {
                stream.definition.id
                for stream in snapshot.catalog.streams(selected_only=True)
            }
        except Exception:  # The marker is a hint, never a failure.
            return None

    async def list(self, status: ProposalStatus | None = None) -> PipelineProposalList:
        statement = select(PipelineProposal).order_by(
            PipelineProposal.created_at.desc(), PipelineProposal.id
        )
        if status is not None:
            statement = statement.where(PipelineProposal.status == status)
        rows = list(await self.session.scalars(statement.limit(MAX_PROPOSALS_LISTED)))
        recorded = (
            await self._recorded()
            if any(row.status == "open" for row in rows)
            else None
        )
        return PipelineProposalList(
            items=[
                PipelineProposalSummary.model_validate(
                    _fields(row, PipelineProposalSummary)
                    | {"missing_readings": _missing(row, recorded)}
                )
                for row in rows
            ],
            capacity=MonitorCapacity(
                running=await monitors_holding_capacity(self.session),
                limit=get_tactic_settings().config.radar_max_active_monitors,
            ),
        )

    async def get(self, identifier: str) -> PipelineProposalView:
        row = await self._row(identifier)
        return proposal_view(
            row, await self._recorded() if row.status == "open" else None
        )

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
        if change.test_run_id is not None:
            await self._tested(change.test_run_id, validation.fingerprint)
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

    async def _tested(self, run_id: str, fingerprint: str | None) -> None:
        """Refuse a test that is no evidence for the design it is handed in with.

        The member who decides reads the test as what this design would have
        reported, so it must have run to its end, and on this design. Titles
        do not count: the fingerprint of a design leaves them out.
        """
        run = await self.session.get(DojoRun, run_id)
        if run is None:
            raise ValidationError(
                f"There is no test run {run_id}. Test the design on history, "
                "then propose it with the id of that run."
            )
        if run.status in ("queued", "running"):
            raise ValidationError(
                "The test is still running. Propose the design once it has finished."
            )
        if run.status != "succeeded":
            raise ValidationError(
                "The test did not run to its end. Propose the design with a "
                "test that finished, or with none."
            )
        try:
            ran = validate_pipeline(
                PipelineDefinition.model_validate(run.config["execution"]["definition"])
            ).fingerprint
        except (KeyError, TypeError, ValueError):
            # A run this release cannot read tested nothing that can be proposed.
            ran = None
        if ran is None or ran != fingerprint:
            raise ValidationError(
                "The test ran another design. Test this design, then propose "
                "it with that test."
            )
        scored = await self.session.scalar(
            select(
                select(DojoRunResult.sequence)
                .where(
                    DojoRunResult.run_id == run_id,
                    DojoRunResult.score.is_not(None),
                )
                .exists()
            )
        )
        if not scored:
            # Zero alarms there says nothing, yet reads as a quiet design.
            raise ValidationError(
                "The test scored nothing: the replay ended inside the design's "
                "warm-up. Test on more days, or with shorter training and "
                "calibration windows, then propose it with that test."
            )

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
