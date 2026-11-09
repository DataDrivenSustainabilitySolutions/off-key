"""Canonical hashes shared by the lightweight pipeline control plane."""

import hashlib
import json
from typing import Any


def digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()
