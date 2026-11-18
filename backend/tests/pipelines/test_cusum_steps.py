"""CUSUM: how far each feature has drifted from its usual level, summed up."""

import pickle
import random

import pytest
from off_key_core.models.pipeline_prepare import (
    default_suffix,
    kernel,
    prepared_bounds,
)
from off_key_core.schemas.pipelines import CusumParameters
from pydantic import ValidationError


def run(step, values):
    state, outputs = step.initial(), []
    for value in values:
        before = pickle.dumps(state)
        state, output = step.advance(state, value)
        assert step.accepts(state)
        assert pickle.dumps(pickle.loads(before)) == before
        outputs.append(output)
    return state, outputs


def series(seed, shift=1.0, start=2000, end=2600, length=3000):
    noise = random.Random(seed)
    return [
        noise.gauss(0, 1) + (shift if start <= index < end else 0)
        for index in range(length)
    ]


def test_a_small_lasting_shift_is_found_soon():
    step = kernel("prepare.cusum", {})
    assert (step.lead, step.window) == (200, 6)
    delays = []
    for seed in range(5):
        _, outputs = run(step, series(seed))
        assert all(item is None for item in outputs[:200])
        rises = [index for index, item in enumerate(outputs) if item and item > 5]
        delays.append(next(index for index in rises if index >= 2000) - 2000)
        # Noise alone rises past the reset rarely.
        assert len([index for index in rises if 200 <= index < 2000]) <= 12
    # A shift of one spread is usually found within a few dozen observations.
    assert sorted(delays)[2] < 40


def test_the_sum_starts_over_and_never_falls_below_zero():
    step = kernel("prepare.cusum", {"window_size": 20})
    values = [0.0, 1.0] * 10 + [10.0] * 30
    _, outputs = run(step, values)
    after = outputs[20:]
    assert min(after) >= 0
    # Past the reset the sum restarts until the new level is learned.
    assert after[0] > 5 and after[-10:] == [0.0] * 10


def test_flat_values_add_nothing():
    _, outputs = run(kernel("prepare.cusum", {"window_size": 10}), [3.0] * 30)
    assert outputs[10:] == [0.0] * 20


def test_settings_suffix_and_bounds():
    assert CusumParameters().model_dump() == {
        "apply_to": None,
        "result": "add",
        "suffix": None,
        "window_size": 200,
        "slack": 0.5,
        "reset_at": 5.0,
    }
    with pytest.raises(ValidationError):
        CusumParameters(window_size=5)
    assert default_suffix("prepare.cusum", {}) == "cusum"
    assert prepared_bounds("prepare.cusum", {}, (-1.0, 4.0)) == (0.0, None)
    assert not kernel("prepare.cusum", {}).accepts((pickle.loads(pickle.dumps(())),))
