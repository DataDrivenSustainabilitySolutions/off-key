"""Proposals: designs handed to a member to decide on, with the reason for them."""

from datetime import UTC, datetime
from uuid import uuid4

from off_key_core.config.logs import log_security_event
from off_key_core.db.collection_runtime import read_collection_runtime
from off_key_core.db.models import (
    Agent,
    DojoLabel,
    DojoRun,
    DojoRunResult,
    PipelineProposal,
    User,
)
from off_key_core.db.pipeline_claims import monitors_holding_capacity
from off_key_core.models.pipelines import validate_pipeline
from off_key_core.schemas.dojo import RunMetrics
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
    ProposalFault,
    ProposalReading,
    ProposalStatus,
    ProposalTest,
)
from sqlalchemy import func, select

from ...config.config import get_tactic_settings
from ...domain import ConflictError, ForbiddenError, NotFoundError, ValidationError
from ..dojo.labels import dataset_labels
from ..dojo.metrics import DojoMetrics
from .library import begin_library_write

# The readings the catalogue records now, by id; None when that is unknown.
Catalogue = dict[str, ProposalReading] | None

# What its author may delete: a proposal that asks nothing of a member any more
# and that no monitor runs on.
DELETABLE_PROPOSALS = ("withdrawn", "declined")


# Read from the catalogue and the test, not stored with the row.
DERIVED = ("missing_readings", "readings", "test")


def _fields(row: PipelineProposal, model) -> dict:
    return {key: getattr(row, key) for key in model.model_fields if key not in DERIVED}


def _derived(row: PipelineProposal, catalogue: Catalogue) -> dict:
    return {
        "missing_readings": _missing(row, catalogue),
        "readings": _readings(row, catalogue),
    }


def proposal_view(
    row: PipelineProposal,
    catalogue: Catalogue = None,
    test: ProposalTest | None = None,
) -> PipelineProposalView:
    return PipelineProposalView.model_validate(
        _fields(row, PipelineProposalView) | _derived(row, catalogue) | {"test": test}
    )


def _missing(row: PipelineProposal, catalogue: Catalogue) -> list[str]:
    """Bound readings gone from the catalogue; only an open proposal can still start."""
    if catalogue is None or row.status != "open":
        return []
    return sorted(set((row.bindings or {}).values()) - set(catalogue))


def _readings(row: PipelineProposal, catalogue: Catalogue) -> list[ProposalReading]:
    """The bound readings by name; one the catalogue lost keeps its id as name."""
    bound = list(dict.fromkeys((row.bindings or {}).values()))
    return [
        (catalogue or {}).get(reading) or ProposalReading(id=reading, label=reading)
        for reading in bound
    ]


def _test_figures(metrics: RunMetrics, labels: list[DojoLabel]) -> ProposalTest:
    notes = {label.id: label.note for label in labels}
    return ProposalTest(
        scored_hours=round(metrics.evaluated_seconds / 3600, 1),
        alarm_share=metrics.diagnostics.alarm_share if metrics.diagnostics else None,
        false_alarms=metrics.false_alarms,
        false_alarms_per_day=metrics.false_alarms_per_day,
        median_delay_seconds=metrics.median_delay_seconds,
        faults=[
            ProposalFault(
                note=notes.get(item.label_id) or "Labelled interval",
                outcome=item.outcome,
                delay_seconds=item.delay_seconds,
            )
            for item in sorted(metrics.labels, key=lambda item: item.start_at)
        ],
    )


def _wrote(row: PipelineProposal, caller: User | Agent) -> bool:
    if isinstance(caller, Agent):
        return row.author_kind == "agent" and row.agent_id == caller.id
    return row.author_kind == "member" and row.author == caller.email


async def require_tested(session, run_id: str, fingerprint: str | None) -> None:
    """Refuse a test that is no evidence for the design it is handed in with.

    The member who reads it takes the test as what this design would have
    reported, so it must have run to its end, and on this design. Titles do
    not count: the fingerprint of a design leaves them out.
    """
    run = await session.get(DojoRun, run_id)
    if run is None:
        raise ValidationError(
            f"There is no test run {run_id}. Test the design on history, "
            "then hand it in with the id of that run."
        )
    if run.status in ("queued", "running"):
        raise ValidationError(
            "The test is still running. Hand the design in once it has finished."
        )
    if run.status != "succeeded":
        raise ValidationError(
            "The test did not run to its end. Hand the design in with a test "
            "that finished, or with none."
        )
    try:
        ran = validate_pipeline(
            PipelineDefinition.model_validate(run.config["execution"]["definition"])
        ).fingerprint
    except (KeyError, TypeError, ValueError):
        # A run this release cannot read tested nothing that can be handed in.
        ran = None
    if ran is None or ran != fingerprint:
        raise ValidationError(
            "The test ran another design. Test this design, then hand it in "
            "with that test."
        )
    scored = await session.scalar(
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
            "calibration windows, then hand it in with that test."
        )


class PipelineProposals:
    def __init__(self, session):
        self.session = session

    async def _catalogue(self) -> Catalogue:
        """The readings a monitor can bind now, named; None when that is unknown."""
        try:
            # A savepoint keeps a failed read from ending the caller's transaction.
            async with self.session.begin_nested():
                snapshot = await read_collection_runtime(self.session)
            document = snapshot.catalog.document
            devices = {device.id: device.label for device in document.devices}
            return {
                stream.definition.id: ProposalReading(
                    id=stream.definition.id,
                    label=stream.definition.label,
                    device=devices.get(stream.definition.device_id or ""),
                    unit=stream.definition.unit,
                )
                for stream in snapshot.catalog.streams(selected_only=True)
            }
        except Exception:  # The names are a hint, never a failure.
            return None

    async def _test(
        self, run_id: str | None, *, calculate: bool
    ) -> ProposalTest | None:
        """The figures of a proposal's test: those already calculated, or with
        `calculate` worked out now within the metrics' time limit."""
        if run_id is None:
            return None
        try:
            # A savepoint keeps a failed read from ending the caller's transaction.
            async with self.session.begin_nested():
                run = await self.session.get(DojoRun, run_id)
                if run is None or run.status != "succeeded":
                    return None
                labels = await dataset_labels(self.session, run.dataset_id)
                metrics = DojoMetrics.cached(run, labels)
                if metrics is None and calculate:
                    metrics = await DojoMetrics(self.session).calculate(run, labels)
                return _test_figures(metrics, labels) if metrics else None
        except Exception:  # The figures are a hint; the proposal reads without.
            return None

    async def list(self, status: ProposalStatus | None = None) -> PipelineProposalList:
        statement = select(PipelineProposal).order_by(
            PipelineProposal.created_at.desc(), PipelineProposal.id
        )
        if status is not None:
            statement = statement.where(PipelineProposal.status == status)
        rows = list(await self.session.scalars(statement.limit(MAX_PROPOSALS_LISTED)))
        catalogue = await self._catalogue() if rows else None
        # The list reads figures already worked out; opening one works them out.
        tests = [await self._test(row.test_run_id, calculate=False) for row in rows]
        return PipelineProposalList(
            items=[
                PipelineProposalSummary.model_validate(
                    _fields(row, PipelineProposalSummary)
                    | _derived(row, catalogue)
                    | {"test": test}
                )
                for row, test in zip(rows, tests, strict=True)
            ],
            capacity=MonitorCapacity(
                running=await monitors_holding_capacity(self.session),
                limit=get_tactic_settings().config.radar_max_active_monitors,
            ),
        )

    async def get(self, identifier: str) -> PipelineProposalView:
        row = await self._row(identifier)
        # Read before the figures: working them out may roll the session back.
        view = proposal_view(row, await self._catalogue())
        test = await self._test(view.test_run_id, calculate=True)
        return view.model_copy(update={"test": test})

    async def create(
        self, change: PipelineProposalCreate, caller: User | Agent
    ) -> PipelineProposalView:
        if isinstance(caller, Agent) and change.rationale is None:
            # Members read it at a glance, and the monitor keeps it once started.
            raise ValidationError(
                "A key proposes a design with a rationale: what it watches, why "
                "this design, the evidence and its limits."
            )
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
            await require_tested(
                self.session, change.test_run_id, validation.fingerprint
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
            rationale=change.rationale.model_dump(mode="json")
            if change.rationale
            else None,
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

    async def remove(self, identifier: str, caller: User | Agent) -> None:
        """Delete a proposal of the caller's own once it was withdrawn or declined.

        A proposal that waits is withdrawn first, and an accepted one stays: it
        is why a monitor runs.
        """
        row = await self._row(identifier, lock=True)
        if not _wrote(row, caller):
            raise ForbiddenError("Only its author can delete a proposal")
        if row.status not in DELETABLE_PROPOSALS:
            raise ConflictError(
                "Withdraw the proposal before deleting it"
                if row.status == "open"
                else "An accepted proposal stays: it is why a monitor runs"
            )
        await self.session.delete(row)
        await self.session.commit()
        log_security_event(
            "pipeline_proposal_deleted",
            caller.name if isinstance(caller, Agent) else caller.email,
            {"proposal_id": identifier, "status": row.status},
        )

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
