from fastapi import APIRouter
from backend.app.api.v1 import chargers

router = APIRouter()

router.include_router(chargers.router, prefix="/chargers", tags=["chargers"])
