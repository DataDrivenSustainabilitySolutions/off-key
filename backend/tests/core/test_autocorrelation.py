"""How a series relates to its own past: the context for choosing time steps."""

import math
import random
from datetime import UTC, datetime, timedelta

from off_key_core.models.autocorrelation import (
    MAX_VALUES,
    autocorrelation,
    on_grid,
)
from off_key_core.models.dataset_profile import profile_series

T0 = datetime(2026, 1, 5, tzinfo=UTC)


def hourly(values):
    return [(T0 + timedelta(hours=index), value) for index, value in enumerate(values)]


def test_too_few_or_flat_values_say_nothing():
    assert autocorrelation(hourly([1.0] * 10)) is None
    assert autocorrelation(hourly([3.0] * 100)) is None


def test_a_daily_cycle_is_found_once_and_named_in_time():
    noise = random.Random(1)
    values = [
        10 * math.sin(2 * math.pi * index / 24) + noise.gauss(0, 1)
        for index in range(24 * 30)
    ]
    found = autocorrelation(hourly(values))
    assert found is not None and found.regular and found.step_seconds == 3600
    season = found.seasons[0]
    assert (season.observations, season.seconds) == (24, 86400)
    # Two and three days are the same cycle again.
    assert all(item.observations % 24 > 2 for item in found.seasons[1:])
    assert not found.persistent


def test_an_autoregressive_series_suggests_its_own_lags():
    noise = random.Random(2)
    values = [0.0, 0.0]
    for _ in range(2000):
        values.append(0.6 * values[-1] - 0.3 * values[-2] + noise.gauss(0, 1))
    found = autocorrelation(hourly(values))
    assert found is not None
    assert {lag.observations for lag in found.suggested_lags[:2]} == {1, 2}
    assert abs(found.pacf[1] + 0.3) < 0.08
    assert all(abs(value) < 0.1 for value in found.pacf[3:10])
    first = found.suggested_lags[0]
    assert first.seconds == 3600 * first.observations


def test_a_random_walk_wanders():
    noise = random.Random(3)
    level, values = 0.0, []
    for _ in range(2000):
        level += noise.gauss(0, 1)
        values.append(level)
    found = autocorrelation(hourly(values))
    assert found is not None and found.persistent


def test_uneven_values_go_on_a_grid_of_the_last_value_before_each_step():
    noise = random.Random(4)
    points, at = [], T0
    for index in range(400):
        at += timedelta(seconds=noise.choice([1, 1, 1, 10]))
        points.append((at, float(index)))
    step, values, regular = on_grid(points)
    assert not regular and step == 1
    assert values[0] == 0.0 and values == sorted(values)
    assert len(values) == int((points[-1][0] - points[0][0]).total_seconds()) + 1


def test_a_long_series_goes_on_a_coarser_grid():
    points = hourly([float(index % 7) for index in range(MAX_VALUES * 3)])
    step, values, regular = on_grid(points)
    assert not regular and len(values) <= MAX_VALUES and step > 3600


def test_a_dojo_profile_reads_the_start_and_the_whole_series():
    values = [math.sin(2 * math.pi * index / 24) for index in range(MAX_VALUES + 500)]
    points = hourly(values)
    profile = profile_series("s1", "load", points, total=len(points) + 100)
    assert (profile.count, profile.interval_seconds) == (len(points) + 100, 3600)
    assert (profile.first, profile.last) == (points[0][0], points[-1][0])
    assert len(profile.autocorrelation) == 2
    assert profile.autocorrelation[0].seasons[0].observations == 24
    assert any("first" in note for note in profile.notes)

    short = profile_series("s2", "flat", hourly([1.0] * 50))
    assert short.autocorrelation == [] and short.notes
    empty = profile_series("s3", "empty", [])
    assert (empty.count, empty.first, empty.interval_seconds) == (0, None, None)


def test_alternating_gaps_are_uneven_and_go_on_a_round_grid():
    points, at = [], T0
    for index in range(600):
        at += timedelta(minutes=2 if index % 2 else 13)
        points.append((at, float(index % 2)))
    step, _values, regular = on_grid(points)
    assert not regular and step == 600
