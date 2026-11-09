"""Domain-level errors for data-service use cases."""


class DomainError(Exception):
    """Base class for domain/application errors."""


class NotFoundError(DomainError):
    """Raised when a requested resource does not exist."""


class ConflictError(DomainError):
    """Raised for conflicts, e.g. duplicate resources."""


class AuthenticationError(DomainError):
    """Raised for authentication/authorization failures."""


class ValidationError(DomainError):
    """Raised for invalid input or domain invariants."""


class InfrastructureError(DomainError):
    """Raised for infrastructure failures (DB/network/system)."""
