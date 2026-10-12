"""Revocable browser sessions; only hashes of their opaque secrets are stored."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text

from .base import Base


class RememberedSession(Base):
    __tablename__ = "remembered_sessions"

    token_hash = Column(Text, primary_key=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_version = Column(Integer, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
