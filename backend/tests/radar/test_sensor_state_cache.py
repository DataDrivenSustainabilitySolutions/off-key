"""Last-known-value alignment: when observations form, wait, hold or drop."""

import pytest
from off_key_core.schemas.radar import MonitorTiming
from off_key_mqtt_radar.state_cache import SensorStateCache


class Clock:
    """Wall and receipt clock in one, moved by the test."""

    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


def _cache(required, clock, **timing):
    return SensorStateCache(
        set(required), MonitorTiming(**timing), clock=clock, monotonic=clock
    )


def _send(cache, clock, sensor, at, value=None):
    clock.now = at
    return cache.update_with_status(
        "entity",
        sensor,
        {sensor: at if value is None else value},
        sample_timestamp=at,
        received_monotonic=at,
    )


def test_an_observation_waits_until_every_reading_has_a_value():
    clock = Clock()
    cache = _cache({"a", "b"}, clock)

    first = _send(cache, clock, "a", 1000)
    assert first.status == "missing_reading"
    assert first.missing_sensors == ("b",)

    formed = _send(cache, clock, "b", 1003)
    assert formed.status == "aligned"
    assert formed.features == {"a": 1000, "b": 1003}
    assert formed.held_sensors == ()
    assert formed.input_timestamps == {"a": 1000, "b": 1003}
    assert formed.sample_timestamp == 1003


def test_readings_at_their_own_moments_form_one_observation_per_interval():
    """Every 20 s, ten seconds apart: the old 5 s skew window never formed one."""
    clock = Clock()
    cache = _cache({"a", "b"}, clock)
    outcomes = []
    for cycle in range(10):
        start = 1000 + 20 * cycle
        outcomes.append(_send(cache, clock, "a", start))
        outcomes.append(_send(cache, clock, "b", start + 10))

    formed = [item for item in outcomes if item.status == "aligned"]
    assert len(formed) == 10
    assert all(item.held_sensors == () for item in formed)
    assert outcomes[0].status == "missing_reading"
    assert {item.status for item in outcomes[1:]} == {"aligned", "waiting_for_reading"}
    assert outcomes[-1].features == {"a": 1180, "b": 1190}


def test_a_slow_reading_is_held_while_a_fast_one_forms_observations():
    clock = Clock()
    cache = _cache({"fast", "slow"}, clock)
    # Learn both intervals: fast every 10 s, slow every 60 s.
    for at in range(1000, 1130, 10):
        _send(cache, clock, "fast", at)
        if at % 60 == 40:
            _send(cache, clock, "slow", at + 3)

    held = _send(cache, clock, "fast", 1130)
    assert held.status == "aligned"
    assert held.held_sensors == ("slow",)
    assert held.features == {"fast": 1130, "slow": 1123}


def test_a_reading_due_before_the_next_arrival_is_waited_for():
    clock = Clock()
    cache = _cache({"a", "b"}, clock)
    for cycle in range(3):
        _send(cache, clock, "a", 1000 + 20 * cycle)
        _send(cache, clock, "b", 1005 + 20 * cycle)

    waiting = _send(cache, clock, "a", 1060)
    assert waiting.status == "waiting_for_reading"
    assert waiting.pending_sensors == ("b",)
    assert _send(cache, clock, "b", 1065).features == {"a": 1060, "b": 1065}


def test_a_reading_that_stops_is_dropped_once_its_value_is_too_old():
    clock = Clock()
    cache = _cache({"fast", "slow"}, clock, hold_intervals=3, minimum_hold_seconds=1)
    for at in range(1000, 1070, 10):
        _send(cache, clock, "fast", at)
        if at in (1000, 1020):
            _send(cache, clock, "slow", at + 1)
    # The slow reading's interval is 20 s, so its value counts for 60 s.
    assert _send(cache, clock, "fast", 1080).status == "aligned"

    dropped = _send(cache, clock, "fast", 1090)
    assert dropped.status == "stale_reading"
    assert dropped.stale_sensors == ("slow",)
    assert dropped.features is None
    # The values were used up: the next arrival tries again on its own.
    assert _send(cache, clock, "fast", 1100).status == "stale_reading"
    # Once the slow reading is back, the fast one is due within ten seconds.
    assert _send(cache, clock, "slow", 1101).status == "waiting_for_reading"
    assert _send(cache, clock, "fast", 1110).features == {"fast": 1110, "slow": 1101}


def test_a_reading_whose_interval_is_unknown_is_waited_for_not_held():
    clock = Clock()
    cache = _cache({"fast", "slow"}, clock)
    _send(cache, clock, "fast", 1000)
    assert _send(cache, clock, "slow", 1001).status == "aligned"

    for at in (1010, 1020, 1030):
        outcome = _send(cache, clock, "fast", at)
        assert outcome.status == "waiting_for_reading"
        assert outcome.pending_sensors == ("slow",)
    assert _send(cache, clock, "slow", 1055).features == {"fast": 1030, "slow": 1055}


def test_a_fresh_value_too_old_for_the_observation_is_dropped():
    clock = Clock()
    cache = _cache({"fast", "slow"}, clock)
    _send(cache, clock, "fast", 1000)
    _send(cache, clock, "slow", 1001)
    for at in (1010, 1020, 1030):
        _send(cache, clock, "fast", at)
    # The fast reading reports every 10 s, so 31 s is beyond its 30 s limit.
    dropped = _send(cache, clock, "slow", 1061)
    assert dropped.status == "stale_reading"
    assert dropped.stale_sensors == ("fast",)


def test_a_value_too_old_before_its_interval_is_known_is_replaced_not_dropped():
    """Nothing says when its next value was due, so there is no gap to count."""
    clock = Clock()
    cache = _cache({"a", "b"}, clock)
    _send(cache, clock, "a", 1000)
    waiting = _send(cache, clock, "b", 1040)
    assert waiting.status == "waiting_for_reading"
    assert waiting.pending_sensors == ("a",)
    assert _send(cache, clock, "a", 1060).features == {"a": 1060, "b": 1040}


def test_without_required_readings_every_value_passes_on_its_own():
    clock = Clock()
    cache = _cache(set(), clock)
    outcome = _send(cache, clock, "x", 1000, value=4.0)
    assert outcome.status == "aligned"
    assert outcome.features == {"x": 4.0}
    assert outcome.sample_timestamp == 1000


@pytest.mark.parametrize(
    ("sensor", "timestamp", "reason"),
    [
        ("a", float("nan"), "observation_nonfinite"),
        ("a", float("inf"), "observation_nonfinite"),
        ("a", 1006.0, "observation_in_future"),
        ("a", 999.0, "observation_duplicate"),
        ("a", 998.0, "observation_regression"),
        ("c", 1000.0, "observation_unexpected_sensor"),
    ],
)
def test_a_rejected_observation_does_not_replace_the_latest_value(
    sensor, timestamp, reason
):
    clock = Clock(1000.0)
    cache = _cache({"a", "b"}, clock)
    cache.update_with_status("entity", "a", {"a": 1}, sample_timestamp=999.0)

    rejected = cache.update_with_status(
        "entity", sensor, {sensor: 999}, sample_timestamp=timestamp
    )
    assert rejected.status == "observation_rejected"
    assert rejected.rejection_reason == reason
    formed = cache.update_with_status("entity", "b", {"b": 2}, sample_timestamp=1000)
    assert formed.features == {"a": 1, "b": 2}
    assert formed.input_timestamps["a"] == 999.0


def test_a_value_without_a_number_is_rejected():
    clock = Clock()
    cache = _cache({"x", "y"}, clock)
    rejected = cache.update_with_status("entity", "x", {"unrelated": 1, "other": 2})
    assert rejected.rejection_reason == "observation_without_value"


def test_a_reading_its_sampler_forwards_late_is_used_from_its_first_value():
    """A sampler that forwards a minute's value 40 s late: nothing says yet when
    the first was due, and once the interval is known 40 s is well inside it."""
    clock = Clock()
    cache = _cache({"a"}, clock)
    for at in (1000, 1060, 1120):
        clock.now = at + 40
        outcome = cache.update_with_status(
            "entity", "a", {"a": at}, sample_timestamp=at
        )
        assert outcome.features == {"a": at}


def test_a_value_older_than_its_readings_limit_is_rejected():
    clock = Clock()
    cache = _cache({"a"}, clock)
    for at in range(1000, 1110, 10):
        _send(cache, clock, "a", at)
    # The reading arrives every 10 s, so its values count for 30 s.
    clock.now = 1200
    rejected = cache.update_with_status("entity", "a", {"a": -1}, sample_timestamp=1150)
    assert rejected.rejection_reason == "observation_too_old"
    assert _send(cache, clock, "a", 1201).features == {"a": 1201}


def test_receipt_age_measures_this_workers_own_queue():
    clock = Clock()
    cache = SensorStateCache(
        {"a"}, MonitorTiming(minimum_hold_seconds=1), clock=clock, monotonic=lambda: 5
    )
    rejected = cache.update_with_status(
        "entity", "a", {"a": 1}, sample_timestamp=999, received_monotonic=3
    )
    assert rejected.rejection_reason == "receipt_too_old"
    assert cache.export_watermarks() == {}


def test_restored_watermarks_reject_replays_and_values_start_over():
    clock = Clock()
    original = _cache({"a", "b"}, clock)
    _send(original, clock, "a", 999)
    restored = _cache({"a", "b"}, clock)
    restored.restore_watermarks(original.export_watermarks())

    assert _send(restored, clock, "a", 999).rejection_reason == "observation_duplicate"
    waiting = _send(restored, clock, "b", 1000)
    assert waiting.status == "missing_reading"
    assert waiting.missing_sensors == ("a",)
    assert _send(restored, clock, "a", 1001).features == {"a": 1001, "b": 1000}


def test_each_reading_reports_its_own_stale_limit():
    clock = Clock()
    cache = _cache({"fast", "slow"}, clock, hold_intervals=3, minimum_hold_seconds=30)
    assert cache.stale_after_seconds() == {"fast": 30, "slow": 30}
    for at in (1000, 1060, 1120):
        _send(cache, clock, "slow", at)
    for at in (1121, 1122, 1123):
        _send(cache, clock, "fast", at)
    assert cache.stale_after_seconds() == {"fast": 30, "slow": 180}


def test_without_required_readings_each_seen_reading_reports_its_limit():
    clock = Clock()
    cache = _cache(set(), clock, minimum_hold_seconds=300)
    assert cache.stale_after_seconds() == {}
    for at in (1000, 1060, 1120):
        _send(cache, clock, "x", at, value=1.0)
    assert cache.stale_after_seconds() == {"x": 300}
