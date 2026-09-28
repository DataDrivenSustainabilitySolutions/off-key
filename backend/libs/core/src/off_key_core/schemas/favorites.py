from pydantic import BaseModel, ConfigDict

__all__ = ["FavoriteCreate"]


class FavoriteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    charger_id: str
