from pydantic import BaseModel, Field

REMEMBERED_SESSION_SECONDS = 30 * 24 * 60 * 60


class RememberedSessionToken(BaseModel):
    token: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
