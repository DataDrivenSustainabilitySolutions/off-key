from fastapi import APIRouter

from . import chargers

router = APIRouter()
router.include_router(chargers.router, prefix="/chargers", tags=["chargers"])
