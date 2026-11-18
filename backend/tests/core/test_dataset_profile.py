"""A Dojo dataset as a whole: each series, how they move together, the labels."""

import math
import random
from datetime import UTC, datetime, timedelta

from off_key_core.models.dataset_profile import (
    level_change,
    pairs,
    profile_dataset,
    profile_series,
    shape,
)

T0 = datetime(2026, 1, 5, tzinfo=UTC)


def hourly(values):
    return [(T0 + timedelta(hours=index), value) for index, value in enumerate(values)]


def test_a_series_profile_says_how_its_values_move_and_where_they_go():
    noise = random.Random(3)
    values = [index / 100 + noise.gauss(0, 1) for index in range(1000)]
    profile = profile_series("s1", "load", hourly(values))
    assert profile.values is not None and profile.values.count == 1000
    assert profile.values.interval_seconds == 3600
    # Ten units over a spread of about three: the level does not stay.
    assert profile.level_change is not None and profile.level_change > 2
    assert profile.persistent and profile.lags
    drawn = profile.shape
    assert drawn is not None and len(drawn.mean) == 48
    assert drawn.mean[0] < drawn.mean[-1]
    assert all(
        low <= mean <= high
        for low, mean, high in zip(drawn.low, drawn.mean, drawn.high, strict=True)
    )
    assert profile.labelled_shift is None


def test_labels_that_show_in_the_level_shift_it():
    values = [0.0] * 200
    for index in range(100, 120):
        values[index] = 5.0
    points = hourly(values)
    labels = [(points[100][0], points[119][0])]
    profile = profile_series("s1", "load", points, labels=labels)
    assert profile.labelled_shift is not None and profile.labelled_shift > 2
    calm = profile_series("s2", "other", hourly([0.0, 1.0] * 100), labels=labels)
    assert calm.labelled_shift == 0


def test_a_flat_or_short_series_has_no_level_change_or_shape():
    assert level_change([1.0] * 100) is None
    assert level_change([1.0, 2.0]) is None
    assert shape(hourly([1.0])) is None


def test_pairs_find_series_that_move_together_and_which_leads():
    noise = random.Random(4)
    driver = [0.0]
    for _ in range(499):
        driver.append(driver[-1] + noise.gauss(0, 1))
    # The follower repeats the driver's moves three hours later.
    follower = [0.0, 0.0, 0.0] + [value + noise.gauss(0, 0.1) for value in driver[:-3]]
    unrelated = [noise.gauss(0, 1) for _ in range(500)]
    step, found = pairs(
        [
            ("driver", hourly(driver)),
            ("follower", hourly(follower)),
            ("noise", hourly(unrelated)),
        ]
    )
    assert step == 3600
    [pair] = found
    assert (pair.first, pair.second) == ("driver", "follower")
    assert pair.lead_seconds == 3 * 3600 and pair.lead_change > 0.9
    # Together, the changes barely match: the lead is what ties them.
    assert abs(pair.change) < 0.3


def test_two_trends_correlate_in_level_but_not_in_change():
    noise = random.Random(5)
    rising = [index + noise.gauss(0, 5) for index in range(400)]
    also = [2 * index + noise.gauss(0, 5) for index in range(400)]
    _, [pair] = pairs([("a", hourly(rising)), ("b", hourly(also))])
    assert pair.level > 0.9 and abs(pair.change) < 0.2


def test_a_dataset_profile_brings_the_series_pairs_and_labels_together():
    wave = [math.sin(2 * math.pi * index / 24) for index in range(24 * 20)]
    points = hourly(wave)
    twice = hourly([2 * value for value in wave])
    labels = [(points[48][0], points[59][0]), (points[200][0], points[205][0])]
    profile = profile_dataset(
        "d1",
        "Load",
        [("s1", "load", points, len(points) + 10), ("s2", "twice", twice, len(twice))],
        labels,
    )
    assert [item.name for item in profile.series] == ["load", "twice"]
    assert profile.series[0].cycles[0].observations == 24
    assert any("first" in note for note in profile.series[0].notes)
    assert (profile.first, profile.last) == (points[0][0], points[-1][0])
    [pair] = profile.pairs
    assert pair.level == 1 and pair.lead_seconds == 0
    assert profile.labels is not None
    assert (profile.labels.count, profile.labels.median_seconds) == (2, 8 * 3600)
    assert 0 < profile.labels.labelled_share < 0.05
    # The full autocorrelation stays with one series' own profile.
    assert "autocorrelation" not in profile.model_dump()["series"][0]


def test_a_dataset_whose_series_do_not_overlap_says_so():
    early = hourly([float(index % 7) for index in range(100)])
    late = [(at + timedelta(days=30), value) for at, value in early]
    profile = profile_dataset(
        "d1", "Apart", [("a", "a", early, 100), ("b", "b", late, 100)]
    )
    assert profile.pairs == [] and profile.step_seconds is None
    assert profile.notes and profile.labels is None
