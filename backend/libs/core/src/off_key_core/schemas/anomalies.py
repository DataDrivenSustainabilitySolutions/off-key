from pydantic import BaseModel

__all__ = ["AnomalyCreate"]


class AnomalyCreate(BaseModel):
    charger_id: str
    timestamp: str
