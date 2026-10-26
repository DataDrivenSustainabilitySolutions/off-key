from fastapi import APIRouter, Depends

from .. import demo
from ..access import current_member, operational_access
from . import (
    anomalies,
    auth,
    charger,
    favorites,
    members,
    monitors,
    system,
    telemetry,
)

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(demo.router, prefix="/demo", tags=["demo"])
protected = APIRouter(dependencies=[Depends(current_member)])

protected.include_router(charger.router, prefix="/chargers", tags=["chargers"])
protected.include_router(telemetry.router, prefix="/telemetry", tags=["telemetry"])
protected.include_router(
    monitors.router,
    prefix="/monitors",
    tags=["monitors"],
    dependencies=[Depends(operational_access)],
)
protected.include_router(favorites.router, prefix="/favorites", tags=["favorites"])
protected.include_router(
    anomalies.router,
    prefix="/anomalies",
    tags=["anomalies"],
    dependencies=[Depends(operational_access)],
)
protected.include_router(system.router, prefix="/system", tags=["system"])

protected.include_router(members.router, prefix="/members", tags=["members"])
router.include_router(protected)
