"""Revocable browser sessions; only hashes of their opaque secrets are stored."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class RememberedSession(Base):
    __tablename__ = "remembered_sessions"

    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    # Every secret issued by rotation from one sign-in shares a family, so reuse
    # of a replaced secret can revoke the whole sign-in.
    family_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_version: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    replaced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
