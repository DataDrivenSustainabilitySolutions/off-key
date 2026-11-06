"""Design library and execution history independent of ephemeral service rows."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


# Lifecycle values the database accepts; migration 023 installs the checks.
RUN_STATUSES = ("reserved", "starting", "running", "stopped", "failed", "cancelled")
ACTIVATION_PHASES = (
    "requested",
    "preflighting",
    "validated",
    "retiring",
    "starting",
    "awaiting_heartbeat",
    "succeeded",
    "cancelling",
    "cancelled",
    "failed",
)


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
    # The last runtime status when the run ended; the service row that held it
    # is deleted by stop and retention purge.
    final_status: Mapped[Any | None] = mapped_column(document(), nullable=True)
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(item) for item in RUN_STATUSES)})",
            name="ck_pipeline_run_status",
        ),
    )


class PipelineRunEvent(Base):
    """One lifecycle event of a run, kept after its service row is purged."""

    __tablename__ = "monitoring_pipeline_run_events"
    id: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False), primary_key=True
    )
    run_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("monitoring_pipeline_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[Any] = mapped_column(document(), nullable=False, default=dict)
    __table_args__ = (
        CheckConstraint(
            "source IN ('radar', 'tactic')", name="ck_pipeline_run_event_source"
        ),
        Index(
            "ix_monitoring_pipeline_run_events_run_time", "run_id", "occurred_at", "id"
        ),
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
    # Each open phase ends as failed once it outlasts the configured budget.
    phase_entered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        CheckConstraint(
            f"phase IN ({', '.join(repr(item) for item in ACTIVATION_PHASES)})",
            name="ck_pipeline_activation_phase",
        ),
    )
