from sqlalchemy import (
    DDL,
    JSON,
    TIMESTAMP,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from ..utils.enum import RoleEnum
from .base import Base
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
from .remembered_sessions import RememberedSession as RememberedSession
from .system import SystemCollectionConfiguration as SystemCollectionConfiguration
from .system import SystemConfiguration as SystemConfiguration
from .system import SystemRevision as SystemRevision
from .table_contracts import monitoring_evidence_table, radar_runtime_checkpoints_table


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("uq_users_email_lower", text("lower(email)"), unique=True),)

    id = Column(Integer, primary_key=True, index=True)
    email = Column(Text, unique=True, index=True, nullable=False)
    hashed_password = Column(Text, nullable=False)
    is_verified = Column(Boolean, default=False)
    is_active = Column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    session_version = Column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    verification_token = Column(Text, nullable=True)
    invitation_expires_at = Column(DateTime(timezone=True), nullable=True)
    reset_token_hash = Column(Text, nullable=True)
    reset_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    role = Column(Enum(RoleEnum), default=RoleEnum.user, nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
    created_at = Column(DateTime, default=func.now(), nullable=False)


class CollectionConfiguration(Base):
    __tablename__ = "collection_configuration"

    id = Column(Integer, primary_key=True)
    revision = Column(Integer, nullable=False, default=0)
    document = Column(JSONB, nullable=False)
    ingress_status = Column(JSONB, nullable=False, default=dict)
    collection_status = Column(JSONB, nullable=False, default=dict)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by = Column(Text, nullable=False)
    __table_args__ = (CheckConstraint("id = 1", name="collection_singleton"),)


class CollectionRevision(Base):
    __tablename__ = "collection_revisions"

    revision = Column(Integer, primary_key=True)
    document = Column(JSONB, nullable=False)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by = Column(Text, nullable=False)


class CollectionBinding(Base):
    __tablename__ = "collection_bindings"

    charger_id = Column(Text, ForeignKey("chargers.charger_id"), primary_key=True)
    source_id = Column(Text, nullable=False)
    local_id = Column(Text, nullable=False)
    __table_args__ = (
        UniqueConstraint("source_id", "local_id", name="uq_collection_source_charger"),
    )


class CollectionState(Base):
    __tablename__ = "collection_state"

    charger_id = Column(Text, ForeignKey("chargers.charger_id"), primary_key=True)
    sensor_key = Column(Text, primary_key=True)
    value = Column(JSONB, nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=False)
    is_snapshot = Column(Boolean, nullable=False)


class Charger(Base):
    __tablename__ = "chargers"

    charger_id = Column(Text, primary_key=True, unique=True, index=True, nullable=False)
    manufacturer_name = Column(Text, unique=False, index=True, nullable=True)
    charger_name = Column(Text, unique=False, index=True, nullable=True)
    firmware_version = Column(Text, unique=False, index=True, nullable=True)
    last_seen = Column(Text, unique=False, index=True, nullable=True)
    state = Column(Text, unique=False, index=True, nullable=True)
    online = Column(Boolean, unique=False, default=True, index=True, nullable=False)
    created = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # MQTT status fields
    mqtt_connected = Column(Boolean, default=False, index=True, nullable=False)
    mqtt_last_message = Column(DateTime(timezone=True), nullable=True, index=True)
    mqtt_subscription_status = Column(
        JSON, nullable=True
    )  # Track subscription status per hierarchy
    mqtt_error_count = Column(Integer, default=0, nullable=False)
    mqtt_last_error = Column(Text, nullable=True)

    # Composite indexes for common query patterns
    __table_args__ = (
        Index("ix_charger_online_state", "online", "state"),
        Index("ix_charger_online_created", "online", "created"),
        Index("ix_charger_mqtt_status", "mqtt_connected", "mqtt_last_message"),
    )


class Telemetry(Base):
    __tablename__ = "telemetry"

    charger_id = Column(Text, primary_key=True, nullable=False)
    timestamp = Column(TIMESTAMP(timezone=True), primary_key=True, nullable=False)
    value = Column(Float, nullable=True)
    type = Column(Text, primary_key=True, nullable=False)
    data_source = Column(Text, nullable=False)
    created = Column(DateTime(timezone=True), server_default=func.now())

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

    id = Column(Text, primary_key=True)
    container_id = Column(
        Text, unique=True, nullable=True
    )  # (for FastAPI + Docker SDK)
    container_name = Column(Text, unique=True, nullable=False)
    mqtt_topic = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=func.now())
    status = Column(Boolean, default=True)
    operational_stage = Column(Text, nullable=False, default="stopped")
    operational_status = Column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False, default=dict
    )
    operational_updated_at = Column(DateTime(timezone=True), nullable=True)
    stop_requested_at = Column(DateTime(timezone=True), nullable=True)
    launch_config = Column(JSON, nullable=True)
    # Desired workload state outlives a controller request or Docker API timeout.
    desired_state = Column(
        Text, nullable=False, default="running", server_default="running"
    )
    lifecycle_version = Column(Integer, nullable=False, default=1, server_default="1")
    config_fingerprint = Column(Text, nullable=True)
    collection_fingerprint = Column(Text, nullable=True)


class RadarRuntimeCheckpoint(Base):
    __table__ = radar_runtime_checkpoints_table(Base.metadata)


class DeploymentMaintenance(Base):
    __tablename__ = "deployment_maintenance"
    __table_args__ = (
        CheckConstraint("id = 1", name="deployment_maintenance_singleton"),
    )

    id = Column(Integer, primary_key=True)
    revision = Column(Text, nullable=False)
    phase = Column(Text, nullable=False)
    monitors = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MqttTopic(Base):
    """
    Utilized by the MQTT Proxy that distributed the topics to the containers.
    Stores the mapping between services and the topics they subscribe to.
    """

    __tablename__ = "mqtt_topics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    service_id = Column(Text, ForeignKey("services.id"), nullable=False, index=True)
    topic = Column(Text, nullable=False)


class Favorite(Base):
    __tablename__ = "favorites"

    favorite_id = Column(
        Integer, primary_key=True, unique=True, index=True, nullable=False
    )

    charger_id = Column(
        Text, ForeignKey("chargers.charger_id"), nullable=False, index=True
    )
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # Composite index for user favorites lookup
    __table_args__ = (Index("ix_favorite_user_charger", "user_id", "charger_id"),)


class Anomaly(Base):
    __tablename__ = "anomalies"

    charger_id = Column(Text, nullable=False, index=True)
    timestamp = Column(TIMESTAMP(timezone=True), nullable=False, index=True)
    telemetry_type = Column(Text, nullable=False, index=True)
    # Empty scope belongs to historical and manually created records. Monitor IDs
    # stay in history after the monitor is deleted, so this is not a foreign key.
    service_id = Column(Text, nullable=False, default="", server_default=text("''"))
    anomaly_type = Column(Text, nullable=False, index=True)
    anomaly_value = Column(Float, nullable=False, index=True)
    # 'tail_pvalue' for rows written by the tail-probability detector.
    # 'conformal_pvalue' for rows written by static conformal monitoring.
    # 'zscore' for legacy rows written by the z-score heuristic.
    # NULL for rows predating this column.
    value_type = Column(Text, nullable=True)
    # Exact telemetry streams involved in this anomaly. Multivariate rows use this
    # to highlight only the charts whose sensors contributed to the aligned vector.
    # NULL means the row predates this column or the writer could not determine it.
    sensor_set = Column(JSON, nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint(
            "charger_id", "timestamp", "telemetry_type", "service_id", name="pk_anomaly"
        ),
        # Composite indexes for common query patterns
        Index("idx_anomaly_lookup", "charger_id", "timestamp", "telemetry_type"),
        Index("idx_anomaly_charger_timestamp", "charger_id", "timestamp"),
        Index(
            "idx_anomaly_timestamp_desc",
            "timestamp",
            postgresql_using="btree",
            postgresql_ops={"timestamp": "DESC"},
        ),
    )


event.listen(
    Anomaly.__table__,
    "after_create",
    DDL(f"SELECT create_hypertable('{Anomaly.__tablename__}', 'timestamp');"),
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
    __tablename__ = "anomaly_identity"

    anomaly_id = Column(
        Text,
        primary_key=True,
        nullable=False,
        server_default=text("gen_random_uuid()::text"),
    )
    charger_id = Column(Text, nullable=False, index=True)
    timestamp = Column(TIMESTAMP(timezone=True), nullable=False, index=True)
    telemetry_type = Column(Text, nullable=False, index=True)
    service_id = Column(Text, nullable=False, default="", server_default=text("''"))
    created = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        UniqueConstraint(
            "charger_id",
            "timestamp",
            "telemetry_type",
            "service_id",
            name="uq_anomaly_identity_target",
        ),
        ForeignKeyConstraint(
            ["charger_id", "timestamp", "telemetry_type", "service_id"],
            [
                "anomalies.charger_id",
                "anomalies.timestamp",
                "anomalies.telemetry_type",
                "anomalies.service_id",
            ],
            ondelete="CASCADE",
            name="fk_anomaly_identity_anomaly",
        ),
        Index(
            "idx_anomaly_identity_charger_timestamp",
            "charger_id",
            "timestamp",
        ),
    )
