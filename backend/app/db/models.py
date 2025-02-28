from sqlalchemy import (
    Column,
    String,
    Boolean,
    DateTime,
    func,
    TIMESTAMP,
    Float,
    UniqueConstraint,
)

from .base import Base


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
