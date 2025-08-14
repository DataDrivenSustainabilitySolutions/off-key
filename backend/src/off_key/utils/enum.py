from enum import Enum


class RoleEnum(str, Enum):
    user = "user"
    admin = "admin"


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    DISABLED = "disabled"
