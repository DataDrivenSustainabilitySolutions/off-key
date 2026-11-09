"""Additive saved-system tables, independent of active collection configuration."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SystemConfiguration(Base):
    __tablename__ = "system_configuration"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    document: Mapped[Any] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (CheckConstraint("id = 1", name="system_singleton"),)


class SystemRevision(Base):
    __tablename__ = "system_revisions"

    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    document: Mapped[Any] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)


class SystemCollectionConfiguration(Base):
    """Sole collection runtime; new catalogue inputs remain Off until opted in."""

    __tablename__ = "system_collection_configuration"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    document: Mapped[Any] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False
    )
    ingress_status: Mapped[Any] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict
    )
    collection_status: Mapped[Any] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)
    __table_args__ = (CheckConstraint("id = 1", name="system_collection_singleton"),)
