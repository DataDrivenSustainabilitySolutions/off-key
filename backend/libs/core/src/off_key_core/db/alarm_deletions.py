"""Short-lived, exact selections for confirmed anomaly deletion."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AlarmDeletion(Base):
    __tablename__ = "alarm_deletions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    alarm_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    # Retaining the result until expiry makes a network retry idempotent.
    deleted_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
