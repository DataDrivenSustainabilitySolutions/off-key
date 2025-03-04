import uuid

from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    func,
    TIMESTAMP,
    Float,
    UniqueConstraint,
    event,
    DDL,
    Integer,
)

from sqlalchemy.dialects.postgresql import UUID

from .base import Base


class Users(Base):

    __tablename__ = "users"  # noqa

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=False)  # Not active until verified
    is_superuser = Column(Boolean, default=False)
    verification_token = Column(UUID(as_uuid=True), nullable=True, default=uuid.uuid4)


class Chargers(Base):

    __tablename__ = "chargers"  # noqa

    charger_id = Column(
        String, primary_key=True, unique=True, index=True, nullable=False
    )
    manufacturer_name = Column(String, unique=False, index=True, nullable=True)
    charger_name = Column(String, unique=False, index=True, nullable=True)
    firmware_version = Column(String, unique=False, index=True, nullable=True)
    last_seen = Column(String, unique=False, index=True, nullable=True)
    state = Column(String, unique=False, index=True, nullable=True)
    online = Column(Boolean, unique=False, default=True, index=True, nullable=False)
    created = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class Telemetry(Base):

    __tablename__ = "telemetry"  # noqa

    charger_id = Column(
        String, primary_key=True, unique=False, index=True, nullable=False
    )
    timestamp = Column(
        TIMESTAMP(timezone=True),
        primary_key=True,
        unique=False,
        index=True,
        nullable=False,
    )
    value = Column(Float, unique=False, index=True, nullable=True)
    type = Column(String, primary_key=True, unique=False, index=True, nullable=False)
    created = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    __table_args__ = (
        UniqueConstraint("charger_id", "timestamp", "type", name="uq_telemetry_entry"),
    )


event.listen(
    Telemetry.__table__,
    "after_create",
    DDL(f"SELECT create_hypertable('{Telemetry.__tablename__}', 'timestamp');"),
)
