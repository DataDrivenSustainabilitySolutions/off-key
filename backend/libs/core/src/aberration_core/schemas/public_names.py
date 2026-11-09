"""Public API names for fields whose stored and internal names differ.

The database and TACTIC keep their names, so stored JSON stays readable by the
previous release. A field declared with ``public(...)`` reads either name and
answers with the public one wherever FastAPI serializes it; ``model_dump()``
without ``by_alias`` still writes the internal name for storage.
"""

from typing import Any

from pydantic import AliasChoices


def public(name: str, internal: str) -> dict[str, Any]:
    """Field options that name the field ``name`` in the API."""
    return {
        "validation_alias": AliasChoices(name, internal),
        "serialization_alias": name,
    }
