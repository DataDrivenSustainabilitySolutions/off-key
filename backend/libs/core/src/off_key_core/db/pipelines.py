"""Design library and execution history independent of ephemeral service rows."""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from .base import Base


def document():
    return JSON().with_variant(JSONB(), "postgresql")


class MonitoringPipeline(Base):
    __tablename__ = "monitoring_pipelines"
    id = Column(Text, primary_key=True)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=False, default="")
    archived = Column(Boolean, nullable=False, default=False)
    is_template = Column(Boolean, nullable=False, default=True, server_default="true")
    version = Column(Integer, nullable=False, default=1)
    draft = Column(document(), nullable=False)
    layout = Column(document(), nullable=False, default=dict)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PipelineRevision(Base):
    __tablename__ = "monitoring_pipeline_revisions"
    id = Column(Text, primary_key=True)
    pipeline_id = Column(
        Text, ForeignKey("monitoring_pipelines.id"), nullable=False, index=True
    )
    number = Column(Integer, nullable=False)
    definition = Column(document(), nullable=False)
    fingerprint = Column(Text, nullable=False)
    catalog_id = Column(Text, nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        UniqueConstraint("pipeline_id", "number", name="uq_pipeline_revision_number"),
    )


class PipelineRun(Base):
    __tablename__ = "monitoring_pipeline_runs"
    id = Column(Text, primary_key=True)
    # Deliberately no service FK: stop and retention purge delete service rows.
    service_id = Column(Text, nullable=False, unique=True)
    revision_id = Column(
        Text, ForeignKey("monitoring_pipeline_revisions.id"), nullable=True
    )
    predecessor_run_id = Column(
        Text, ForeignKey("monitoring_pipeline_runs.id"), nullable=True
    )
    execution = Column(document(), nullable=True)
    launch_config = Column(document(), nullable=False)
    layout = Column(document(), nullable=False, default=dict)
    binding_metadata = Column(document(), nullable=True)
    status = Column(Text, nullable=False, default="reserved")
    error = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at = Column(DateTime(timezone=True), nullable=True)


class PipelineActivation(Base):
    __tablename__ = "monitoring_pipeline_activations"
    id = Column(Text, primary_key=True)
    idempotency_key = Column(Text, nullable=False, unique=True)
    request_hash = Column(Text, nullable=False)
    revision_id = Column(
        Text, ForeignKey("monitoring_pipeline_revisions.id"), nullable=False
    )
    service_id = Column(Text, nullable=False, unique=True)
    run_id = Column(Text, ForeignKey("monitoring_pipeline_runs.id"), nullable=False)
    predecessor_service_id = Column(Text, nullable=True)
    predecessor_lifecycle_version = Column(Integer, nullable=True)
    retirement_started = Column(Boolean, nullable=False, default=False)
    heartbeat_deadline = Column(DateTime(timezone=True), nullable=True)
    phase = Column(Text, nullable=False, default="requested", index=True)
    claim_topics = Column(document(), nullable=False)
    collection_fingerprint = Column(Text, nullable=False)
    launch_config = Column(document(), nullable=False)
    preflight = Column(document(), nullable=True)
    image_digest = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    cancel_requested = Column(Boolean, nullable=False, default=False)
    controller_token = Column(Text, nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
