from sqlalchemy import (
    Column,
    Enum,
    Index,
    PrimaryKeyConstraint,
    Text,
    Boolean,
    DateTime,
    func,
    TIMESTAMP,
    Float,
    UniqueConstraint,
    event,
    DDL,
    Integer,
    JSON,
    ForeignKey,
    text,
)

from .base import Base
from ..utils.enum import RoleEnum
from ..config import get_retention_days
from ..config.logs import logger

# Cache retention days at module load to prevent mid-run environment changes
_RETENTION_DAYS = get_retention_days()


class User(Base):
    __tablename__ = "users"  # noqa

    id = Column(Integer, primary_key=True, index=True)
    email = Column(Text, unique=True, index=True, nullable=False)
    hashed_password = Column(Text, nullable=False)
    is_verified = Column(Boolean, default=False)
    verification_token = Column(Text, nullable=True)
    role = Column(Enum(RoleEnum), default=RoleEnum.user, nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )
    created_at = Column(DateTime, default=func.now(), nullable=False)


class Charger(Base):
    __tablename__ = "chargers"  # noqa

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
    __tablename__ = "telemetry"  # noqa

    charger_id = Column(
        Text, primary_key=True, unique=False, index=True, nullable=False
    )
    timestamp = Column(
        TIMESTAMP(timezone=True),
        primary_key=True,
        unique=False,
        index=True,
        nullable=False,
    )
    value = Column(Float, unique=False, index=True, nullable=True)
    type = Column(Text, primary_key=True, unique=False, index=True, nullable=False)
    data_source = Column(Text, nullable=False, index=True)
    created = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        UniqueConstraint("charger_id", "timestamp", "type", name="uq_telemetry_entry"),
        # Composite indexes for common query patterns
        Index("ix_telemetry_charger_timestamp", "charger_id", "timestamp"),
        Index("ix_telemetry_charger_type", "charger_id", "type"),
        Index(
            "ix_telemetry_timestamp_desc",
            "timestamp",
            postgresql_using="btree",
            postgresql_ops={"timestamp": "DESC"},
        ),
    )


event.listen(
    Telemetry.__table__,
    "after_create",
    DDL(f"SELECT create_hypertable('{Telemetry.__tablename__}', 'timestamp');"),
)


def _add_telemetry_retention_policy(target, connection, **kw):
    """
    Add TimescaleDB retention policy to the telemetry hypertable.

    This function is called after the hypertable is created to set up
    automatic data retention based on the configured retention period.
    Uses the cached retention_days value to prevent mid-run changes.
    """
    # Use cached value (already validated as integer 1-365)
    retention_policy_sql = text(
        f"""
        SELECT add_retention_policy(
            '{Telemetry.__tablename__}',
            INTERVAL '{_RETENTION_DAYS} days',
            if_not_exists => true
        );
        """
    )
    connection.execute(retention_policy_sql)
    logger.info(
        f"TimescaleDB retention policy set for '{Telemetry.__tablename__}': "
        f"{_RETENTION_DAYS} days"
    )


event.listen(
    Telemetry.__table__,
    "after_create",
    _add_telemetry_retention_policy,
)


class MonitoringService(Base):
    __tablename__ = "services"

    id = Column(Text, primary_key=True)
    container_id = Column(
        Text, unique=True, nullable=True
    )  # (for FastAPI + Docker SDK)
    container_name = Column(Text, unique=True, nullable=False)
    stateful_set_name = Column(
        Text, unique=True, nullable=True
    )  # (for Kubernetes StatefulSet)
    mqtt_topic = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=func.now())
    status = Column(Boolean, default=True)


class MqttTopic(Base):
    """
    Utilized by the MQTT Proxy that distributed the topics to the containers.
    Stores the mapping between services and the topics they subscribe to.
    """

    __tablename__ = "mqtt_topics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    service_id = Column(Text, ForeignKey("services.id"), nullable=False)
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
    anomaly_type = Column(Text, nullable=False, index=True)
    anomaly_value = Column(Float, nullable=False, index=True)

    __table_args__ = (
        PrimaryKeyConstraint(
            "charger_id", "timestamp", "telemetry_type", name="pk_anomaly"
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


class ModelRegistry(Base):
    """
    Database-backed ML model registry.

    Stores model definitions, hyperparameter schemas, and metadata.
    Replaces hardcoded MODEL_REGISTRY and PREPROCESSOR_REGISTRY.
    """

    __tablename__ = "model_registry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_type = Column(Text, unique=True, nullable=False, index=True)
    category = Column(Text, nullable=False, index=True)  # 'model' or 'preprocessor'
    family = Column(Text, nullable=False, index=True)  # 'forest', 'distance', etc.

    # Model metadata
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    complexity = Column(Text, nullable=True)  # 'low', 'medium', 'high'
    memory_usage = Column(Text, nullable=True)  # 'low', 'medium', 'high'

    # Import configuration
    import_paths = Column(JSON, nullable=False)  # List of import paths to try

    # Parameter schema (JSON Schema format)
    parameter_schema = Column(JSON, nullable=False)
    default_parameters = Column(JSON, nullable=False, default=dict)

    # Versioning and lifecycle
    version = Column(Text, nullable=False, default="1.0.0")
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    requires_special_handling = Column(
        Boolean, default=False, nullable=False
    )  # For KNN, etc.

    # Timestamps
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(
        DateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    # Indexes for efficient queries
    __table_args__ = (
        Index("ix_model_registry_active_category", "is_active", "category"),
        Index("ix_model_registry_type_active", "model_type", "is_active"),
    )
