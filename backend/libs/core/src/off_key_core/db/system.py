"""Additive saved-system tables, independent of active collection configuration."""

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB

from .base import Base


class SystemConfiguration(Base):
    __tablename__ = "system_configuration"

    id = Column(Integer, primary_key=True)
    revision = Column(Integer, nullable=False, default=0)
    document = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by = Column(Text, nullable=False)
    __table_args__ = (CheckConstraint("id = 1", name="system_singleton"),)


class SystemRevision(Base):
    __tablename__ = "system_revisions"

    revision = Column(Integer, primary_key=True)
    document = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by = Column(Text, nullable=False)


class SystemCollectionConfiguration(Base):
    """Sole collection runtime; new catalogue inputs remain Off until opted in."""

    __tablename__ = "system_collection_configuration"

    id = Column(Integer, primary_key=True)
    revision = Column(Integer, nullable=False)
    document = Column(JSONB().with_variant(JSON(), "sqlite"), nullable=False)
    ingress_status = Column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict
    )
    collection_status = Column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False, default=dict
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by = Column(Text, nullable=False)
    __table_args__ = (CheckConstraint("id = 1", name="system_collection_singleton"),)
