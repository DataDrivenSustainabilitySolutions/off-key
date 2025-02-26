from fastapi import APIRouter

from . import chargers, telemetry

router = APIRouter()

router.include_router(chargers.router, prefix="/chargers", tags=["chargers"])
router.include_router(telemetry.router, prefix="/telemetry", tags=["telemetry"])
