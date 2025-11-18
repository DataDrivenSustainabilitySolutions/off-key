"""
Bridges access to core configuration helpers.

Keeping this indirection allows the db-sync service to use relative imports
while still depending on shared logic from ``off_key_core``.
"""

from off_key_core.config import get_retention_days

__all__ = ["get_retention_days"]
