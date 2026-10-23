"""One persisted claim projection for legacy services and graph activations."""

from collections.abc import Iterable

from sqlalchemy import or_, select

from ..utils.mqtt_topics import mqtt_topic_filters_overlap
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


def first_overlap(
    requested: Iterable[str], claimed: Iterable[str]
) -> tuple[str, str] | None:
    """Return the first requested/claimed filter pair that can match one topic."""
    claimed = [str(topic) for topic in claimed]
    for topic in requested:
        for other in claimed:
            if mqtt_topic_filters_overlap(topic, other):
                return topic, other
    return None


def claim_owners(active, pending, *, released: Iterable[str] = ()) -> set[str]:
    """Services that hold capacity: running owners not being replaced, plus
    every pending activation's target."""
    retiring = {item.predecessor_service_id for item in pending} | set(released)
    return {item.id for item in active if item.id not in retiring} | {
        item.service_id for item in pending
    }
