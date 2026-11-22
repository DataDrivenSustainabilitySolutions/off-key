import math

import pytest
from off_key_core.utils.numbers import finite_float


@pytest.mark.parametrize(("value", "expected"), [(3, 3.0), (-1.5, -1.5), (0, 0.0)])
def test_finite_numbers_become_floats(value, expected):
    assert finite_float(value) == expected
    assert isinstance(finite_float(value), float)


@pytest.mark.parametrize(
    "value", [True, False, math.nan, math.inf, -math.inf, "1.0", None, [1]]
)
def test_everything_else_is_none(value):
    assert finite_float(value) is None
