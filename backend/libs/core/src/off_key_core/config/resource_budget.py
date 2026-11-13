"""Validated resource quantities of RADAR workloads."""

import re
from decimal import Decimal

DEFAULT_RADAR_MEMORY_MB = 384
DEFAULT_RADAR_MAX_ACTIVE_MONITORS = 20
MEBIBYTE = 1024 * 1024
_MAX_QUANTITY = 2**63 - 1
_MEMORY_SIZE = re.compile(
    r"^([0-9]+(?:\.[0-9]+)?)\s*((?:[kmgt](?:i?b)?|b)?)$", re.IGNORECASE
)


def _whole_positive_quantity(value: Decimal, label: str) -> int:
    if (
        not value.is_finite()
        or value <= 0
        or value > _MAX_QUANTITY
        or value != value.to_integral_value()
    ):
        raise ValueError(f"{label} must represent a positive whole quantity")
    return int(value)


def parse_memory_bytes(value: str) -> int:
    """Parse memory units without accepting malformed or zero limits."""
    match = _MEMORY_SIZE.fullmatch(value.strip())
    if match is None:
        raise ValueError("Memory must be positive bytes or a k/m/g/t memory size")
    number, unit = match.groups()
    prefix = unit.lower()[:1]
    multiplier = 1024 ** {"k": 1, "m": 2, "g": 3, "t": 4}.get(prefix, 0)
    return _whole_positive_quantity(Decimal(number) * multiplier, "Memory")


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
