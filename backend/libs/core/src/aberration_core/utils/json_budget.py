"""Conservative JSON transport budgets without constructing oversized strings."""

import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel


def bounded_utf8_text(value: str, limit: int) -> str:
    prefix = value[:limit].encode("utf-8")
    if len(value) <= limit and len(prefix) <= limit:
        return value
    return prefix[: limit - 3].decode("utf-8", errors="ignore") + "…"


def fits_json_budget(value: Any, budget: int) -> bool:
    """ASCII escaping conservatively bounds both UTF-8 and ASCII JSON outputs."""
    return json_size_up_to(value, budget) <= budget


def json_size_up_to(value: Any, budget: int) -> int:
    if budget < 0:
        return 1
    if isinstance(value, BaseModel):
        value = {name: getattr(value, name) for name in type(value).model_fields}
    if isinstance(value, Mapping):
        return _mapping_size(value, budget)
    if isinstance(value, (tuple, list)):
        size = 2
        separator = 0
        for item in value:
            size += separator + json_size_up_to(item, budget - size - separator)
            if size > budget:
                return size
            separator = 1
        return size
    if isinstance(value, str) and len(value) > budget:
        return budget + 1
    try:
        return len(json.dumps(value, ensure_ascii=True, allow_nan=False))
    except (ValueError, TypeError):
        return budget + 1


def _mapping_size(value, budget):
    size = 2
    separator = 0
    for key, item in value.items():
        size += separator + json_size_up_to(str(key), budget - size - separator) + 1
        size += json_size_up_to(item, budget - size)
        if size > budget:
            return size
        separator = 1
    return size
