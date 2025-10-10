from pydantic import BaseModel

__all__ = ["FavoriteCreate"]


class FavoriteCreate(BaseModel):
    user_id: int
    charger_id: str
