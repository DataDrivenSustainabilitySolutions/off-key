"""Number checks shared by services that store untrusted values as JSON."""

import math
from typing import Any


def finite_float(value: Any) -> float | None:
    """``value`` as a float when it is a finite int or float, else None.

    Booleans are not numbers here, although Python treats them as ints.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None
