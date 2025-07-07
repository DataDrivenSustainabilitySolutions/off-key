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
)

from .base import Base
from ..utils.enum import RoleEnum


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

    # Composite indexes for common query patterns
    __table_args__ = (
        Index('ix_charger_online_state', 'online', 'state'),
        Index('ix_charger_online_created', 'online', 'created'),
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
    created = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        UniqueConstraint("charger_id", "timestamp", "type", name="uq_telemetry_entry"),
        # Composite indexes for common query patterns
        Index('ix_telemetry_charger_timestamp', 'charger_id', 'timestamp'),
        Index('ix_telemetry_charger_type', 'charger_id', 'type'),
        Index('ix_telemetry_timestamp_desc', 'timestamp', postgresql_using='btree', postgresql_ops={'timestamp': 'DESC'}),
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
    __table_args__ = (
        Index('ix_favorite_user_charger', 'user_id', 'charger_id'),
    )



class Anomaly(Base):
    __tablename__ = "anomalies"

    charger_id = Column(Text, nullable=False, index=True)
    timestamp = Column(TIMESTAMP(timezone=True), nullable=False, index=True)
    telemetry_type = Column(Text, nullable=False, index=True)
    anomaly_type = Column(Text, nullable=False, index=True)
    anomaly_value = Column(Float, nullable=False, index=True)

    __table_args__ = (
        PrimaryKeyConstraint("charger_id", "timestamp",
        "telemetry_type", name="pk_anomaly"),
        # Composite indexes for common query patterns
        Index("idx_anomaly_lookup", "charger_id", "timestamp", "telemetry_type"),
        Index("idx_anomaly_charger_timestamp", "charger_id", "timestamp"),
        Index("idx_anomaly_timestamp_desc", "timestamp", postgresql_using='btree', postgresql_ops={'timestamp': 'DESC'}),
    )

event.listen(
    Anomaly.__table__,
    "after_create",
    DDL(f"SELECT create_hypertable('{Anomaly.__tablename__}', 'timestamp');"),
)
