"""The block library: named chains of steps the composer copies into designs."""

from datetime import UTC, datetime
from uuid import uuid4

from off_key_core.db.models import PipelineBlock
from off_key_core.models.pipeline_blocks import require_block_steps
from off_key_core.schemas.pipelines import (
    MAX_BLOCKS,
    PipelineBlockCreate,
    PipelineBlockList,
    PipelineBlockView,
)
from sqlalchemy import func, select

from ...domain import ConflictError, NotFoundError
from .library import begin_library_write


def block_view(row: PipelineBlock) -> PipelineBlockView:
    return PipelineBlockView.model_validate(
        {key: getattr(row, key) for key in PipelineBlockView.model_fields}
    )


class PipelineBlocks:
    def __init__(self, session):
        self.session = session

    async def list(self) -> PipelineBlockList:
        rows = await self.session.scalars(
            select(PipelineBlock)
            .order_by(func.lower(PipelineBlock.name), PipelineBlock.id)
            .limit(MAX_BLOCKS)
        )
        return PipelineBlockList(items=[block_view(row) for row in rows])

    async def create(self, change: PipelineBlockCreate) -> PipelineBlockView:
        # The write lock makes the name and the count hold until the commit.
        await begin_library_write(self.session)
        require_block_steps(change.steps)
        if await self.session.scalar(
            select(PipelineBlock.id).where(PipelineBlock.name == change.name)
        ):
            raise ConflictError(
                f"A block named {change.name} already exists. Choose another name."
            )
        count = await self.session.scalar(
            select(func.count()).select_from(PipelineBlock)
        )
        if count >= MAX_BLOCKS:
            raise ConflictError(
                f"The library holds {MAX_BLOCKS} blocks. "
                "Delete one before saving another."
            )
        row = PipelineBlock(
            id=str(uuid4()),
            name=change.name,
            description=change.description,
            steps=[step.model_dump(mode="json") for step in change.steps],
            created_at=datetime.now(UTC),
        )
        self.session.add(row)
        await self.session.commit()
        return block_view(row)

    async def remove(self, identifier: str) -> None:
        """Delete a block. Designs that copied its steps keep them."""
        await begin_library_write(self.session)
        row = await self.session.get(PipelineBlock, identifier)
        if row is None:
            raise NotFoundError("Block not found")
        await self.session.delete(row)
        await self.session.commit()
