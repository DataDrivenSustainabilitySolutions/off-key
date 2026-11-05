from fastapi import APIRouter, Depends
from off_key_core.auth.permissions import Permission

from ..access import current_member, writes_require
from . import (
    anomalies,
    auth,
    charger,
    favorites,
    members,
    monitors,
    roles,
    system,
    telemetry,
)

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["auth"])
protected = APIRouter(dependencies=[Depends(current_member)])

protected.include_router(charger.router, prefix="/chargers", tags=["chargers"])
protected.include_router(telemetry.router, prefix="/telemetry", tags=["telemetry"])
protected.include_router(
    monitors.router,
    prefix="/monitors",
    tags=["monitors"],
    dependencies=[Depends(writes_require(Permission.manage_monitors))],
)
protected.include_router(favorites.router, prefix="/favorites", tags=["favorites"])
protected.include_router(
    anomalies.router,
    prefix="/anomalies",
    tags=["anomalies"],
    dependencies=[Depends(writes_require(Permission.manage_alarms))],
)
protected.include_router(
    anomalies.query_router, prefix="/anomalies", tags=["anomalies"]
)
protected.include_router(system.router, prefix="/system", tags=["system"])

protected.include_router(members.router, prefix="/members", tags=["members"])
protected.include_router(roles.router, tags=["roles"])
router.include_router(protected)
