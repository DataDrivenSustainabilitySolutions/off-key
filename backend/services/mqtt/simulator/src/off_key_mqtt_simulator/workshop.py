"""Small, domain-neutral MQTT fixture for the generic spatial workspace."""

import math


def build_workshop_messages(
    tick: int, interval_seconds: float
) -> tuple[tuple[str, dict[str, float | bool | str]], ...]:
    """Build one bounded tick of synthetic readings, without storing history."""
    elapsed = tick * interval_seconds
    running = elapsed % 40 < 30
    return (
        (
            "workshop/office/environment",
            {
                "temperature": round(22 + 1.8 * math.sin(elapsed / 24), 3),
                "humidity": round(48 + 5 * math.cos(elapsed / 31), 3),
            },
        ),
        (
            "workshop/workbench/vibration",
            {
                "rms": round(1.6 + 0.6 * math.sin(elapsed / 4) if running else 0.04, 3),
            },
        ),
        (
            "workshop/workbench/status",
            {
                "running": running,
                "mode": "Operating" if running else "Idle",
                "cycle_id": f"cycle-{int(elapsed // 40) + 1:04d}",
            },
        ),
    )
