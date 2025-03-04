from fastapi import APIRouter

from . import charger, telemetry, user

router = APIRouter()

router.include_router(user.router, prefix="/users", tags=["users"])
router.include_router(charger.router, prefix="/chargers", tags=["chargers"])
router.include_router(telemetry.router, prefix="/telemetry", tags=["telemetry"])
