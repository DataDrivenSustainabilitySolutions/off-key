from datetime import datetime
from typing import Any

from sqlalchemy import (
    DDL,
    JSON,
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..auth.permissions import (
    MEMBER_ROLE,
    ROLE_ID_PATTERN,
    Permission,
    role_permissions,
)
from .access_sessions import RevokedAccessToken as RevokedAccessToken
from .base import Base
from .dojo import DojoDataset as DojoDataset
from .dojo import DojoLabel as DojoLabel
from .dojo import DojoPoint as DojoPoint
from .dojo import DojoRun as DojoRun
from .dojo import DojoRunResult as DojoRunResult
from .dojo import DojoSeries as DojoSeries
from .evidence_clock import MonitoringEvidenceClock as MonitoringEvidenceClock
from .pipelines import (
    MonitoringPipeline as MonitoringPipeline,
)
from .pipelines import (
    PipelineActivation as PipelineActivation,
)
from .pipelines import (
    PipelineRevision as PipelineRevision,
)
from .pipelines import (
    PipelineRun as PipelineRun,
)
from .pipelines import (
    PipelineRunEvent as PipelineRunEvent,
)
from .remembered_sessions import RememberedSession as RememberedSession
from .system import SystemCollectionConfiguration as SystemCollectionConfiguration
from .system import SystemConfiguration as SystemConfiguration
from .system import SystemRevision as SystemRevision
from .table_contracts import (
    anomalies_table,
    anomaly_identity_table,
    monitoring_evidence_table,
    radar_runtime_checkpoints_table,
)

# Migration 023 adds this check; databases adopted before it lack it.
DESIRED_STATE_CHECK = "ck_services_desired_state"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("uq_users_email_lower", text("lower(email)"), unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(Text, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    is_verified: Mapped[bool | None] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    session_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    verification_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    invitation_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reset_token_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    reset_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The role's id; migration 021 turned the former user/admin enum into it.
    role: Mapped[str] = mapped_column(
        Text, ForeignKey("member_roles.id"), default=MEMBER_ROLE, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), nullable=False
    )
    # Loaded with every member, because every protected request checks it.
    member_role: Mapped["MemberRole"] = relationship(lazy="selectin")

    @property
    def permissions(self) -> list[Permission]:
        granted = self.member_role.permissions if self.member_role else ()
        return role_permissions(self.role, granted)


class MemberRole(Base):
    """A named set of permissions. Each member holds exactly one role."""

    __tablename__ = "member_roles"
    __table_args__ = (
        CheckConstraint(f"id ~ '{ROLE_ID_PATTERN}'", name="ck_member_role_id"),
        Index("uq_member_roles_name_lower", text("lower(name)"), unique=True),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Permission values; 'admin' holds every permission whatever is stored.
    permissions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class CollectionConfiguration(Base):
    __tablename__ = "collection_configuration"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    document: Mapped[Any] = mapped_column(JSONB, nullable=False)
    ingress_status: Mapped[Any] = mapped_column(JSONB, nullable=False, default=dict)
    collection_status: Mapped[Any] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (CheckConstraint("id = 1", name="collection_singleton"),)


class CollectionRevision(Base):
    __tablename__ = "collection_revisions"

    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    document: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)


class CollectionBinding(Base):
    __tablename__ = "collection_bindings"

    charger_id: Mapped[str] = mapped_column(
        Text, ForeignKey("chargers.charger_id"), primary_key=True
    )
    source_id: Mapped[str] = mapped_column(Text, nullable=False)
    local_id: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (
        UniqueConstraint("source_id", "local_id", name="uq_collection_source_charger"),
    )


class CollectionState(Base):
    __tablename__ = "collection_state"

    charger_id: Mapped[str] = mapped_column(
        Text, ForeignKey("chargers.charger_id"), primary_key=True
    )
    sensor_key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    is_snapshot: Mapped[bool] = mapped_column(Boolean, nullable=False)


class Charger(Base):
    __tablename__ = "chargers"

    charger_id: Mapped[str] = mapped_column(
        Text, primary_key=True, unique=True, index=True, nullable=False
    )
    manufacturer_name: Mapped[str | None] = mapped_column(
        Text, unique=False, index=True, nullable=True
    )
    charger_name: Mapped[str | None] = mapped_column(
        Text, unique=False, index=True, nullable=True
    )
    firmware_version: Mapped[str | None] = mapped_column(
        Text, unique=False, index=True, nullable=True
    )
    last_seen: Mapped[str | None] = mapped_column(
        Text, unique=False, index=True, nullable=True
    )
    state: Mapped[str | None] = mapped_column(
        Text, unique=False, index=True, nullable=True
    )
    online: Mapped[bool] = mapped_column(
        Boolean, unique=False, default=True, index=True, nullable=False
    )
    created: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    # MQTT status fields
    mqtt_connected: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True, nullable=False
    )
    mqtt_last_message: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    mqtt_subscription_status: Mapped[Any | None] = mapped_column(
        JSON, nullable=True
    )  # Track subscription status per hierarchy
    mqtt_error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mqtt_last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Composite indexes for common query patterns
    __table_args__ = (
        Index("ix_charger_online_state", "online", "state"),
        Index("ix_charger_online_created", "online", "created"),
        Index("ix_charger_mqtt_status", "mqtt_connected", "mqtt_last_message"),
    )


class Telemetry(Base):
    __tablename__ = "telemetry"

    charger_id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), primary_key=True, nullable=False
    )
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    type: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    data_source: Mapped[str] = mapped_column(Text, nullable=False)
    created: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # The primary key serves upserts; TimescaleDB adds its own time index.
    __table_args__ = (
        # History reads, newest first.
        Index(
            "ix_telemetry_charger_type_timestamp_desc",
            "charger_id",
            "type",
            "timestamp",
            postgresql_using="btree",
            postgresql_ops={"timestamp": "DESC"},
        ),
        # Cursor reads by arrival time.
        Index(
            "ix_telemetry_charger_type_created_timestamp",
            "charger_id",
            "type",
            "created",
            "timestamp",
        ),
    )


event.listen(
    Telemetry.__table__,
    "after_create",
    DDL(f"SELECT create_hypertable('{Telemetry.__tablename__}', 'timestamp');"),
)


class MonitoringService(Base):
    __tablename__ = "services"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    container_id: Mapped[str | None] = mapped_column(
        Text, unique=True, nullable=True
    )  # (for FastAPI + Docker SDK)
    container_name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    mqtt_topic: Mapped[Any] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=func.now())
    status: Mapped[bool | None] = mapped_column(Boolean, default=True)
    operational_stage: Mapped[str] = mapped_column(
        Text, nullable=False, default="stopped"
    )
    operational_status: Mapped[Any] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=dict
    )
    operational_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stop_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    launch_config: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    # Desired workload state outlives a controller request or Docker API timeout.
    desired_state: Mapped[str] = mapped_column(
        Text, nullable=False, default="running", server_default="running"
    )
    lifecycle_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    config_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    collection_fingerprint: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (
        CheckConstraint(
            "desired_state IN ('running', 'stopped', 'deleted')",
            name=DESIRED_STATE_CHECK,
        ),
    )


class RadarRuntimeCheckpoint(Base):
    __table__ = radar_runtime_checkpoints_table(Base.metadata)


class DeploymentMaintenance(Base):
    __tablename__ = "deployment_maintenance"
    __table_args__ = (
        CheckConstraint("id = 1", name="deployment_maintenance_singleton"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[str] = mapped_column(Text, nullable=False)
    phase: Mapped[str] = mapped_column(Text, nullable=False)
    monitors: Mapped[Any] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class MqttTopic(Base):
    """
    Utilized by the MQTT Proxy that distributed the topics to the containers.
    Stores the mapping between services and the topics they subscribe to.
    """

    __tablename__ = "mqtt_topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_id: Mapped[str] = mapped_column(
        Text, ForeignKey("services.id"), nullable=False, index=True
    )
    topic: Mapped[str] = mapped_column(Text, nullable=False)


class MemberFavorite(Base):
    """A catalogue device or reading, or a monitor, a member starred."""

    __tablename__ = "member_favorites"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    # Not a foreign key: readings and monitors live in documents and services
    # that come and go, and a favorite stays until the member removes it.
    item_id: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "kind IN ('device', 'reading', 'monitor')", name="ck_member_favorite_kind"
        ),
    )


class Anomaly(Base):
    __table__ = anomalies_table(Base.metadata)


event.listen(
    Anomaly.__table__,
    "after_create",
    DDL(f"SELECT create_hypertable('{Anomaly.__table__.name}', 'timestamp');"),
)


class MonitoringEvidence(Base):
    """Per-inference conformal and e-process evidence for chart overlays."""

    __table__ = monitoring_evidence_table(Base.metadata)


event.listen(
    MonitoringEvidence.__table__,
    "after_create",
    DDL(
        "SELECT create_hypertable('monitoring_evidence', 'timestamp', "
        "if_not_exists => true);"
    ),
)


class AnomalyIdentity(Base):
    __table__ = anomaly_identity_table(Base.metadata)
