"""Validated resource quantities shared by workload configuration and scheduling."""

import re
from decimal import Decimal, DecimalException

from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_RADAR_MEMORY_MB = 384
DEFAULT_RADAR_MAX_ACTIVE_MONITORS = 20
MEBIBYTE = 1024 * 1024
_MAX_DOCKER_QUANTITY = 2**63 - 1
_MEMORY_SIZE = re.compile(
    r"^([0-9]+(?:\.[0-9]+)?)\s*((?:[kmgt](?:i?b)?|b)?)$", re.IGNORECASE
)


def _whole_positive_quantity(value: Decimal, label: str) -> int:
    if (
        not value.is_finite()
        or value <= 0
        or value > _MAX_DOCKER_QUANTITY
        or value != value.to_integral_value()
    ):
        raise ValueError(f"{label} must represent a positive whole quantity")
    return int(value)


def parse_memory_bytes(value: str) -> int:
    """Parse Docker memory units without accepting malformed or zero limits."""
    match = _MEMORY_SIZE.fullmatch(value.strip())
    if match is None:
        raise ValueError("Memory must be positive bytes or a k/m/g/t memory size")
    number, unit = match.groups()
    prefix = unit.lower()[:1]
    multiplier = 1024 ** {"k": 1, "m": 2, "g": 3, "t": 4}.get(prefix, 0)
    return _whole_positive_quantity(Decimal(number) * multiplier, "Memory")


def parse_cpu_nanos(value: str) -> int:
    """Validate a positive Docker CPU quantity down to one nanocpu."""
    try:
        quantity = Decimal(value.strip()) * 1_000_000_000
    except DecimalException as error:
        raise ValueError("CPU must be a positive finite number") from error
    return _whole_positive_quantity(quantity, "CPU")


def validate_ingress_budget(
    max_queue_size: int,
    max_payload_bytes: int,
    memory_limit_mb: int,
) -> None:
    """Raw queued payloads alone must not consume the worker's entire target."""
    if max_queue_size * max_payload_bytes >= memory_limit_mb * MEBIBYTE:
        raise ValueError(
            "Maximum queued MQTT payload bytes must be below the RADAR memory budget"
        )


class RadarResourceBudget(BaseModel):
    """Hard limits and the capacity that Swarm must reserve for each worker."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    memory_limit_bytes: int = Field(gt=0, le=_MAX_DOCKER_QUANTITY)
    cpu_limit_nanos: int = Field(gt=0, le=_MAX_DOCKER_QUANTITY)
    memory_reservation_bytes: int = Field(gt=0, le=_MAX_DOCKER_QUANTITY)
    cpu_reservation_nanos: int = Field(gt=0, le=_MAX_DOCKER_QUANTITY)

    @model_validator(mode="after")
    def validate_reservations(self) -> "RadarResourceBudget":
        if self.memory_reservation_bytes > self.memory_limit_bytes:
            raise ValueError("Memory reservation cannot exceed its hard limit")
        if self.cpu_reservation_nanos > self.cpu_limit_nanos:
            raise ValueError("CPU reservation cannot exceed its hard limit")
        return self
