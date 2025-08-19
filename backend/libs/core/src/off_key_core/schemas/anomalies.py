from pydantic import BaseModel


class AnomalyCreate(BaseModel):
    charger_id: str
    timestamp: str
