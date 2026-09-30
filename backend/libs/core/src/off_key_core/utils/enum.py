from enum import StrEnum


class RoleEnum(StrEnum):
    user = "user"
    admin = "admin"


class HealthStatus(StrEnum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DISABLED = "disabled"
    DEGRADED = "degraded"
