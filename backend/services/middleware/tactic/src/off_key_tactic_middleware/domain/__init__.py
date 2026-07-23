"""Domain primitives for TACTIC data services."""

from .errors import (
    AuthenticationError,
    ConflictError,
    DomainError,
    InfrastructureError,
    NotFoundError,
    ValidationError,
)

__all__ = [
    "DomainError",
    "NotFoundError",
    "ConflictError",
    "AuthenticationError",
    "ValidationError",
    "InfrastructureError",
]
