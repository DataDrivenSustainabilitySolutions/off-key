"""Favorites: the devices, readings and monitors a member starred."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

__all__ = ["MAX_FAVORITES", "Favorite", "FavoriteKind", "FavoriteRef"]

# Kept small so a member's favorites always load in one response.
MAX_FAVORITES = 256

FavoriteKind = Literal["device", "reading", "monitor"]
FavoriteId = Annotated[
    str,
    StringConstraints(min_length=1, max_length=280, pattern=r"^[^\x00-\x1f\x7f]+$"),
]


class FavoriteRef(BaseModel):
    """What a favorite points at.

    `device` takes a catalogue device id, `reading` a catalogue reading id and
    `monitor` a `monitor_id`. Ids are not checked against the catalogue, so a
    favorite outlives what it points at until the member removes it.
    """

    model_config = ConfigDict(extra="forbid")

    kind: FavoriteKind
    id: FavoriteId


class Favorite(FavoriteRef):
    """A favorite and when the member added it."""

    created_at: datetime
