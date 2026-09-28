from fastapi import APIRouter, Depends

from ..access import current_member, operational_access
from . import (
    anomalies,
    auth,
    charger,
    collection,
    favorites,
    members,
    monitors,
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
    dependencies=[Depends(operational_access)],
)
protected.include_router(favorites.router, prefix="/favorites", tags=["favorites"])
protected.include_router(
    anomalies.router,
    prefix="/anomalies",
    tags=["anomalies"],
    dependencies=[Depends(operational_access)],
)
protected.include_router(collection.router, prefix="/sources", tags=["collection"])

protected.include_router(members.router, prefix="/members", tags=["members"])
router.include_router(protected)
