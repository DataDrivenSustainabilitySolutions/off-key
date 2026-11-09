"""Serialize deployment maintenance with catalog and monitor mutations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import DeploymentMaintenance


class DeploymentInProgressError(RuntimeError):
    """A deployment currently owns the catalog and monitor lifecycle."""


async def require_application_writes(
    session: AsyncSession, *, deployment_revision: str | None = None
) -> None:
    # Callers hold the collection configuration lock before checking this row.
    operation = await session.scalar(
        select(DeploymentMaintenance).where(DeploymentMaintenance.id == 1)
    )
    if (
        operation is not None
        and operation.phase != "complete"
        and deployment_revision != operation.revision
    ):
        raise DeploymentInProgressError(
            "A production release is in progress. Please retry after it finishes."
        )
