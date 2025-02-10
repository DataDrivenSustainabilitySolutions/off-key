from sqlalchemy import Column, Integer, String, Boolean, DateTime, func

from .base import Base


class Chargers(Base):

    __tablename__ = "chargers"  # noqa

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    charger_id = Column(String, unique=True, index=True, nullable=False)
    manufacturer_name = Column(String, unique=False, index=True, nullable=True)
    charger_name = Column(String, unique=True, index=True, nullable=False)
    firmware_version = Column(String, unique=False, index=True, nullable=True)
    last_seen = Column(String, unique=False, index=True, nullable=True)
    state = Column(String, unique=False, index=True, nullable=True)
    online = Column(Boolean, default=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())


class Sensors(Base):

    __tablename__ = "sensors"  # noqa

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    charger_id = Column(String, unique=True, index=True, nullable=False)
    sensor_type = Column(String, unique=False, index=True, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
