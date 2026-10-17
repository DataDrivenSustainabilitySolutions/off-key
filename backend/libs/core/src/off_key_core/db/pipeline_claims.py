"""One persisted claim projection for legacy services and graph activations."""

from sqlalchemy import or_, select

from .models import MonitoringService, PipelineActivation

TERMINAL_ACTIVATION_PHASES = frozenset({"succeeded", "cancelled", "failed"})


def monitor_claim_condition():
    """Desired running intent retains its claim across a derived status outage."""
    return or_(
        MonitoringService.status.is_(True), MonitoringService.desired_state == "running"
    )


async def pending_activations(session):
    return list(
        (
            await session.scalars(
                select(PipelineActivation).where(
                    PipelineActivation.phase.not_in(TERMINAL_ACTIVATION_PHASES)
                )
            )
        ).all()
    )


async def require_no_pipeline_activation(session) -> None:
    if await pending_activations(session):
        raise ValueError(
            "Finish or cancel pending pipeline activations before beginning a release"
        )
