"""
# SQLAlchemy Models
"""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, func

from backend.app.db.database import Base


class Chargers(Base):
    """
    Database model for active chargers.
    """

    __tablename__ = "chargers"  # noqa

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    charger_id = Column(String, unique=True, index=True, nullable=False)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<Charger(id={self.id}, charger_id={self.charger_id}, is_active={self.is_active}, created_at={self.created_at})>"
