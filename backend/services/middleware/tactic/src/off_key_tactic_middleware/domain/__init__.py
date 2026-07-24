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
    "AuthenticationError",
    "ConflictError",
    "DomainError",
    "InfrastructureError",
    "NotFoundError",
    "ValidationError",
]
