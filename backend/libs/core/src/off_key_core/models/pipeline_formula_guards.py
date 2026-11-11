"""Conservative feature bounds on the selected side of a formula condition."""

import math
from collections.abc import Mapping
from typing import TYPE_CHECKING

from .pipeline_prepare import Bounds

if TYPE_CHECKING:
    from .pipeline_formula import Term

_OPPOSITE = {">": "<=", ">=": "<", "<": ">=", "<=": ">", "==": "!=", "!=": "=="}
_REVERSE = {">": "<", ">=": "<=", "<": ">", "<=": ">=", "==": "==", "!=": "!="}


def _literal(term: "Term") -> float | None:
    if term.kind == "number":
        return term.value
    if term.kind == "negate":
        value = _literal(term.args[0])
        return -value if value is not None else None
    return None


def assume(
    term: "Term",
    truth: bool,
    bounds: Mapping[str, Bounds],
    nonzero: frozenset[str],
) -> tuple[dict[str, Bounds], frozenset[str]] | None:
    """Narrow simple comparisons; None means this branch cannot be selected.

    Disjunctions that cannot be represented by one interval retain their old
    bounds. A separate nonzero fact handles guards such as x != 0.
    """
    if term.kind == "not":
        return assume(term.args[0], not truth, bounds, nonzero)
    if term.kind == "logic" and (term.value == "and") == truth:
        current = (dict(bounds), nonzero)
        for operand in term.args:
            current = assume(operand, truth, *current)
            if current is None:
                return None
        return current
    narrowed = dict(bounds)
    if term.kind != "compare":
        return narrowed, nonzero
    return _comparison(term, truth, narrowed, nonzero)


def _comparison(term, truth, narrowed, nonzero):
    left, right = term.args
    op = term.value if truth else _OPPOSITE[term.value]
    if right.kind == "name" and _literal(left) is not None:
        left, right, op = right, left, _REVERSE[op]
    value = _literal(right)
    if left.kind != "name" or value is None:
        return narrowed, nonzero
    name = left.value
    low, high = narrowed.get(name, (None, None))
    low = -math.inf if low is None else low
    high = math.inf if high is None else high
    low, high = _restrict(low, high, op, value)
    if op == "!=" and value == 0:
        nonzero = nonzero | {name}
    if low > high or low == math.inf or high == -math.inf:
        return None
    narrowed[name] = (
        None if low == -math.inf else low,
        None if high == math.inf else high,
    )
    return narrowed, nonzero


def _restrict(low: float, high: float, op: str, value: float) -> tuple[float, float]:
    if op == ">":
        low = max(low, math.nextafter(value, math.inf))
    elif op == ">=":
        low = max(low, value)
    elif op == "<":
        high = min(high, math.nextafter(value, -math.inf))
    elif op == "<=":
        high = min(high, value)
    elif op == "==":
        low, high = max(low, value), min(high, value)
    else:
        if low == value:
            low = math.nextafter(value, math.inf)
        if high == value:
            high = math.nextafter(value, -math.inf)
    return low, high
