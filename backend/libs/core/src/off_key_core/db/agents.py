"""Agents that sign in with a key in place of a password."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Agent(Base):
    """An agent and the digest of its key. Deleting the row revokes the key."""

    __tablename__ = "agents"
    __table_args__ = (Index("uq_agents_name_lower", text("lower(name)"), unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    key_hint: Mapped[str] = mapped_column(Text, nullable=False)
    # Every key designs, tests and proposes; starting services is allowed per key.
    may_start: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # The member's email, kept as text so it outlives the member.
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
