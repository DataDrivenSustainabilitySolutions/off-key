"""Revocable browser sessions; only hashes of their opaque secrets are stored."""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text

from .base import Base


class RememberedSession(Base):
    __tablename__ = "remembered_sessions"

    token_hash = Column(Text, primary_key=True)
    # Every secret issued by rotation from one sign-in shares a family, so reuse
    # of a replaced secret can revoke the whole sign-in.
    family_id = Column(Text, nullable=False, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_version = Column(Integer, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    replaced_at = Column(DateTime(timezone=True), nullable=True)
