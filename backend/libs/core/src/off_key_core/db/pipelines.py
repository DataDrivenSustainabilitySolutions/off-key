"""Design library and execution history independent of ephemeral service rows."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


def document():
    return JSON().with_variant(JSONB(), "postgresql")


class MonitoringPipeline(Base):
    __tablename__ = "monitoring_pipelines"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_template: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    draft: Mapped[Any] = mapped_column(document(), nullable=False)
    layout: Mapped[Any] = mapped_column(document(), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PipelineRevision(Base):
    __tablename__ = "monitoring_pipeline_revisions"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    pipeline_id: Mapped[str] = mapped_column(
        Text, ForeignKey("monitoring_pipelines.id"), nullable=False, index=True
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[Any] = mapped_column(document(), nullable=False)
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    catalog_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("pipeline_id", "number", name="uq_pipeline_revision_number"),
    )


class PipelineRun(Base):
    __tablename__ = "monitoring_pipeline_runs"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    # Deliberately no service FK: stop and retention purge delete service rows.
    service_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    revision_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("monitoring_pipeline_revisions.id"), nullable=True
    )
    predecessor_run_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("monitoring_pipeline_runs.id"), nullable=True
    )
    execution: Mapped[Any | None] = mapped_column(document(), nullable=True)
    launch_config: Mapped[Any] = mapped_column(document(), nullable=False)
    layout: Mapped[Any] = mapped_column(document(), nullable=False, default=dict)
    binding_metadata: Mapped[Any | None] = mapped_column(document(), nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="reserved")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PipelineActivation(Base):
    __tablename__ = "monitoring_pipeline_activations"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    request_hash: Mapped[str] = mapped_column(Text, nullable=False)
    revision_id: Mapped[str] = mapped_column(
        Text, ForeignKey("monitoring_pipeline_revisions.id"), nullable=False
    )
    service_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    run_id: Mapped[str] = mapped_column(
        Text, ForeignKey("monitoring_pipeline_runs.id"), nullable=False
    )
    predecessor_service_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    predecessor_lifecycle_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    retirement_started: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    heartbeat_deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    phase: Mapped[str] = mapped_column(
        Text, nullable=False, default="requested", index=True
    )
    claim_topics: Mapped[Any] = mapped_column(document(), nullable=False)
    collection_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    launch_config: Mapped[Any] = mapped_column(document(), nullable=False)
    preflight: Mapped[Any | None] = mapped_column(document(), nullable=True)
    image_digest: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    controller_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
