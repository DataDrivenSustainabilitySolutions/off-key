"""A reading's profile: when it has values, how far they reach and how they move."""

import math
import random
from datetime import UTC, datetime, timedelta

from off_key_core.models.reading_profile import (
    MAX_BUCKETS,
    bucket_width,
    profile_reading,
)

END = datetime(2026, 11, 12, 12, tzinfo=UTC)
QUARTER = timedelta(minutes=15)


def window(days):
    return END - timedelta(days=days), END


def extremes(start, end, level, skip=lambda at: False):
    """The lowest and highest value of each quarter of an hour, as the range
    query returns them."""
    points = []
    at = start
    while at < end:
        if not skip(at):
            low, high = level(at)
            points += [
                (at + timedelta(minutes=1), low),
                (at + timedelta(minutes=9), high),
            ]
        at += QUARTER
    return points


def daily(at):
    """Ten around fifty with the time of day, and a little noise on top."""
    middle = 50 + 10 * math.sin(2 * math.pi * (at.hour + at.minute / 60) / 24)
    return middle - 1, middle + 1


def test_a_window_without_values_answers_with_nulls():
    start, end = window(14)
    profile = profile_reading("r1", start, end, [], [])
    assert profile.model_dump(mode="json") == {
        "reading_id": "r1",
        "start": "2026-10-29T12:00:00Z",
        "end": "2026-11-12T12:00:00Z",
        "bucket_seconds": 900.0,
        "first": None,
        "last": None,
        "coverage": None,
        "longest_outage_seconds": None,
        "minimum": None,
        "maximum": None,
        "daily_rhythm": None,
        "weekly_rhythm": None,
        "level_change": None,
        "recent": None,
    }


def test_the_window_says_where_values_are_and_how_far_they_reach():
    start, end = window(14)
    outage = (start + timedelta(days=3), start + timedelta(days=3, hours=5))
    points = extremes(start, end, daily, lambda at: outage[0] <= at < outage[1])
    profile = profile_reading("r1", start, end, points, [])
    assert profile.first == start + timedelta(minutes=1)
    assert profile.last == end - timedelta(minutes=6)
    # Twenty of 1344 quarters of an hour are empty, in one run of five hours.
    assert profile.coverage == round(1324 / 1344, 3)
    assert profile.longest_outage_seconds == 5 * 3600
    assert (profile.minimum, profile.maximum) == (39.0, 61.0)
    # The level is where it was a day's cycle earlier.
    assert profile.level_change == 0
    assert profile.recent is None


def test_coverage_counts_from_the_first_value_not_from_the_start_of_the_window():
    start, end = window(14)
    began = end - timedelta(days=3)
    profile = profile_reading("r1", start, end, extremes(began, end, daily), [])
    assert profile.first == began + timedelta(minutes=1)
    assert profile.coverage == 1
    assert profile.longest_outage_seconds == 0


def test_rhythm_is_the_share_of_variation_the_clock_explains():
    start, end = window(28)
    assert (
        profile_reading("r1", start, end, extremes(start, end, daily), []).daily_rhythm
        >= 0.99
    )

    def weekdays(at):
        # Busy by day on weekdays, idle at the weekend and at night.
        busy = at.weekday() < 5 and 8 <= at.hour < 18
        return (40, 42) if busy else (1, 2)

    working = profile_reading("r1", start, end, extremes(start, end, weekdays), [])
    assert working.weekly_rhythm >= 0.99
    # The hour alone explains a part; the weekday explains the rest.
    assert 0.2 < working.daily_rhythm < working.weekly_rhythm - 0.2

    noise = random.Random(7)

    def random_level(at):
        value = noise.gauss(50, 5)
        return value, value

    shapeless = profile_reading(
        "r1", start, end, extremes(start, end, random_level), []
    )
    # Many small groups do not explain noise.
    assert shapeless.daily_rhythm <= 0.05 and shapeless.weekly_rhythm <= 0.05


def test_rhythm_and_level_change_need_days_to_speak_of():
    start, end = window(1)
    day = profile_reading("r1", start, end, extremes(start, end, daily), [])
    assert (day.daily_rhythm, day.weekly_rhythm, day.level_change) == (None, None, None)
    start, end = window(7)
    week = profile_reading("r1", start, end, extremes(start, end, daily), [])
    assert week.daily_rhythm >= 0.99 and week.weekly_rhythm is None

    def rising(at):
        value = (at - start) / timedelta(days=1)
        return value, value

    climbing = profile_reading("r1", start, end, extremes(start, end, rising), [])
    # Six days up over a spread of about two days.
    assert 2.5 < climbing.level_change < 3.5
    flat = profile_reading(
        "r1", start, end, extremes(start, end, lambda at: (5, 5)), []
    )
    assert (flat.daily_rhythm, flat.level_change) == (None, None)
    assert (flat.minimum, flat.maximum) == (5, 5)


def test_a_long_window_has_wider_buckets():
    start, end = window(90)
    assert bucket_width(*window(20)) == QUARTER
    width = bucket_width(start, end)
    assert width == (end - start) / MAX_BUCKETS > QUARTER
    profile = profile_reading("r1", start, end, extremes(start, end, daily), [])
    assert profile.bucket_seconds == 3888
    assert profile.coverage == 1
    assert profile.daily_rhythm > 0.9


def newest(count, step=10, value=lambda index: float(index)):
    return [
        (END - timedelta(seconds=step * (count - 1 - index)), value(index))
        for index in range(count)
    ]


def test_recent_values_say_how_the_reading_arrives():
    start, end = window(1)
    samples = newest(100)
    # A pause of two minutes, and three arrivals that carried no value.
    samples = [
        (at - timedelta(seconds=110) if index < 50 else at, value)
        for index, (at, value) in enumerate(samples)
    ]
    samples[10:13] = [(at, None) for at, _ in samples[10:13]]
    recent = profile_reading("r1", start, end, [], samples).recent
    assert (recent.count, recent.missing) == (97, 3)
    assert (recent.first, recent.last) == (samples[0][0], END)
    assert (recent.interval_seconds, recent.interval_p90_seconds) == (10, 10)
    # The three missing values leave one pause of forty seconds, short of a gap.
    assert (recent.gaps, recent.longest_gap_seconds) == (1, 120)
    assert (recent.mean, recent.median) == (50.6907, 51)
    assert (recent.p05, recent.p95) == (4.8, 94.2)
    assert recent.typical_change == 1
    assert (recent.flat_share, recent.longest_flat_seconds) == (0, 0)
    assert (recent.distinct, recent.levels) == (97, None)


def test_recent_values_say_how_long_the_reading_stays_the_same():
    start, end = window(1)
    # Off, on for a minute, off again: a state and not a measurement.
    samples = newest(60, value=lambda index: 1.0 if 20 <= index < 26 else 0.0)
    recent = profile_reading("r1", start, end, [], samples).recent
    assert (recent.distinct, recent.levels) == (2, [0, 1])
    assert recent.flat_share == round(57 / 59, 3)
    assert recent.longest_flat_seconds == 330
    assert (recent.typical_change, recent.spread) == (0, 0.3)
    # A reading that reports on change has no usual interval to speak of.
    irregular = newest(4, value=float)
    irregular[0] = (irregular[0][0] - timedelta(hours=3), 0.0)
    sparse = profile_reading("r1", start, end, [], irregular).recent
    assert sparse.interval_seconds == 10 and sparse.interval_p90_seconds > 8000
    one = profile_reading("r1", start, end, [], newest(1)).recent
    assert (one.count, one.interval_seconds, one.gaps) == (1, None, 0)
    assert (one.typical_change, one.flat_share, one.longest_flat_seconds) == (
        None,
        None,
        0,
    )


def test_values_from_before_the_window_are_left_out():
    start, end = window(1)
    old = [(start - timedelta(days=2), 7.0), (start - timedelta(seconds=1), 8.0)]
    profile = profile_reading("r1", start, end, [(at, value) for at, value in old], old)
    assert profile.first is None and profile.recent is None
    kept = profile_reading("r1", start, end, [], [*old, (END, 9.0)]).recent
    assert (kept.count, kept.mean) == (1, 9)
