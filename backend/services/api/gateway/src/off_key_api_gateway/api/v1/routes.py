from fastapi import APIRouter, Depends
from off_key_core.auth.permissions import Permission

from ..access import current_member, writes_require
from . import (
    anomalies,
    auth,
    catalogue,
    charger,
    dojo,
    evidence,
    favorites,
    members,
    monitors,
    pipelines,
    roles,
    telemetry,
)

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["auth"])
protected = APIRouter(dependencies=[Depends(current_member)])

protected.include_router(charger.router, prefix="/chargers", tags=["chargers"])
protected.include_router(telemetry.router, prefix="/telemetry", tags=["telemetry"])
manage_monitors = writes_require(Permission.manage_monitors)
protected.include_router(
    monitors.router,
    prefix="/monitors",
    tags=["monitors"],
    dependencies=[Depends(manage_monitors)],
)
protected.include_router(
    pipelines.router,
    prefix="/pipelines",
    tags=["pipelines"],
    dependencies=[Depends(manage_monitors)],
)
protected.include_router(
    pipelines.components_router, prefix="/pipeline-components", tags=["pipelines"]
)
protected.include_router(
    pipelines.activations_router,
    prefix="/pipeline-activations",
    tags=["pipelines"],
    dependencies=[Depends(manage_monitors)],
)
protected.include_router(
    monitors.detectors_router, prefix="/detectors", tags=["detectors"]
)
protected.include_router(evidence.router, prefix="/evidence", tags=["evidence"])
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
protected.include_router(catalogue.router, prefix="/catalogue", tags=["catalogue"])
protected.include_router(
    catalogue.brokers_router, prefix="/brokers", tags=["catalogue"]
)
protected.include_router(
    catalogue.recording_router, prefix="/recording", tags=["recording"]
)
protected.include_router(
    catalogue.storage_router, prefix="/storage", tags=["recording"]
)
protected.include_router(catalogue.live_router, prefix="/live", tags=["live"])

protected.include_router(members.me_router, prefix="/me", tags=["members"])
protected.include_router(members.router, prefix="/members", tags=["members"])
protected.include_router(
    members.invitations_router, prefix="/invitations", tags=["members"]
)
protected.include_router(roles.router, tags=["roles"])
protected.include_router(dojo.router, prefix="/dojo", tags=["dojo"])
router.include_router(protected)
