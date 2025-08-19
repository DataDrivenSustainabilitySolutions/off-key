from fastapi import APIRouter


from . import charger, telemetry, auth, favorites, services, anomalies

router = APIRouter()

router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(charger.router, prefix="/chargers", tags=["chargers"])
router.include_router(telemetry.router, prefix="/telemetry", tags=["telemetry"])
router.include_router(services.router, prefix="/services", tags=["services"])
router.include_router(favorites.router, prefix="/favorites", tags=["favorites"])
router.include_router(anomalies.router, prefix="/anomalies", tags=["anomalies"])
