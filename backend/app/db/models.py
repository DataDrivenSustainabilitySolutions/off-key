from sqlalchemy import Column, String, Boolean, DateTime, func, TIMESTAMP, Float, Integer

from .base import Base


class Chargers(Base):

    __tablename__ = "chargers"  # noqa

    charger_id = Column(String, primary_key=True, unique=True, index=True, nullable=False)
    manufacturer_name = Column(String, unique=False, index=True, nullable=True)
    charger_name = Column(String, unique=True, index=True, nullable=False)
    firmware_version = Column(String, unique=False, index=True, nullable=True)
    last_seen = Column(String, unique=False, index=True, nullable=True)
    state = Column(String, unique=False, index=True, nullable=True)
    online = Column(Boolean, unique=False, default=True, index=True, nullable=False)
    created = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class Telemetry(Base):

    __tablename__ = "telemetry"  # noqa

    id = Column(Integer, primary_key=True, autoincrement=True)
    charger_id = Column(String, unique=True, index=True, nullable=False)
    timestamp = Column(TIMESTAMP(timezone=True), index=True, nullable=False)
    value = Column(Float, unique=False, index=True, nullable=True)
    type = Column(String, unique=False, index=True, nullable=False)
    created = Column(DateTime(timezone=True), server_default=func.now(), index=True)
