"""
Pydantic schemas for TACTIC middleware service.

These schemas define the data transfer objects used for API requests and responses.
"""

from pydantic import BaseModel

# =============================================================================
# User Schemas
# =============================================================================


class UserLoginRequest(BaseModel):
    """Request schema for user login."""

    email: str
    password: str


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "UserLoginRequest",
]
