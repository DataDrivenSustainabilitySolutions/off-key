"""Hashes of signed-out bearer tokens, retained only until their expiry."""

from datetime import datetime

from sqlalchemy import DateTime, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class RevokedAccessToken(Base):
    __tablename__ = "revoked_access_tokens"
    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    __table_args__ = (Index("ix_revoked_access_tokens_expiry", "expires_at"),)
