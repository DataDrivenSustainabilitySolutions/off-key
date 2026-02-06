"""Domain primitives for TACTIC data services."""

from .errors import (
    DomainError,
    NotFoundError,
    ConflictError,
    AuthenticationError,
    ValidationError,
    InfrastructureError,
)

__all__ = [
    "DomainError",
    "NotFoundError",
    "ConflictError",
    "AuthenticationError",
    "ValidationError",
    "InfrastructureError",
]
