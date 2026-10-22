"""Tests for sensor alignment cache freshness gating."""

import pytest
from off_key_mqtt_radar import state_cache as state_cache_module
from off_key_mqtt_radar.state_cache import SensorStateCache


def test_sensor_state_cache_blocks_stale_sensor_and_recovers(monkeypatch):
    now = {"value": 100.0}

    def _fake_time() -> float:
        return now["value"]

    monkeypatch.setattr(state_cache_module.time, "time", _fake_time)

    cache = SensorStateCache(
        required_sensors={"sine", "cosine"},
        ttl_seconds=3600,
        max_sensor_age_seconds=5.0,
    )

    first = cache.update_with_status("charger-1", "sine", {"sine": 1.0})
    assert first.status == "waiting_for_all"
    assert first.missing_sensors == ("cosine",)

    now["value"] = 101.0
    second = cache.update_with_status(
        "charger-1",
        "cosine",
        {"cosine": 2.0},
        sample_timestamp=101.0,
    )
    assert second.status == "aligned_emit"
    assert second.features == {"sine": 1.0, "cosine": 2.0}
    assert second.sample_timestamp == 101.0
    assert second.input_timestamps == {
        "sine": 100.0,
        "cosine": 101.0,
    }

    # cosine arrives again much later while sine is stale
    now["value"] = 110.0
    stale = cache.update_with_status("charger-1", "cosine", {"cosine": 2.1})
    assert stale.status == "stale_sensor_block"
    assert stale.stale_sensors == ("sine",)

    # Once stale sensor recovers, alignment resumes immediately
    now["value"] = 111.0
    recovered = cache.update_with_status("charger-1", "sine", {"sine": 1.2})
    assert recovered.status == "aligned_emit"
    assert recovered.features == {"sine": 1.2, "cosine": 2.1}


def test_sensor_state_cache_waits_until_all_required_sensors_arrive(monkeypatch):
    now = {"value": 200.0}

    def _fake_time() -> float:
        return now["value"]

    monkeypatch.setattr(state_cache_module.time, "time", _fake_time)

    cache = SensorStateCache(required_sensors={"a", "b", "c"})

    update = cache.update_with_status("charger-2", "a", {"a": 1.0})
    assert update.status == "waiting_for_all"
    assert set(update.missing_sensors) == {"b", "c"}

    now["value"] = 201.0
    update = cache.update_with_status("charger-2", "b", {"b": 2.0})
    assert update.status == "waiting_for_all"
    assert set(update.missing_sensors) == {"c"}

    now["value"] = 202.0
    update = cache.update_with_status("charger-2", "c", {"c": 3.0})
    assert update.status == "aligned_emit"
    assert update.features == {"a": 1.0, "b": 2.0, "c": 3.0}


def test_sensor_state_cache_strict_barrier_waits_for_new_values_from_all(monkeypatch):
    now = {"value": 300.0}

    def _fake_time() -> float:
        return now["value"]

    monkeypatch.setattr(state_cache_module.time, "time", _fake_time)

    cache = SensorStateCache(required_sensors={"x", "y"})

    assert (
        cache.update_with_status("charger-3", "x", {"x": 1.0}).status
        == "waiting_for_all"
    )
    now["value"] = 301.0
    assert (
        cache.update_with_status("charger-3", "y", {"y": 2.0}).status == "aligned_emit"
    )

    # Only x updates; strict barrier should wait for y to advance.
    now["value"] = 302.0
    waiting = cache.update_with_status("charger-3", "x", {"x": 1.1})
    assert waiting.status == "waiting_for_barrier"
    assert waiting.pending_sensors == ("y",)

    now["value"] = 303.0
    emitted = cache.update_with_status("charger-3", "y", {"y": 2.1})
    assert emitted.status == "aligned_emit"
    assert emitted.features == {"x": 1.1, "y": 2.1}


def test_sensor_state_cache_preserves_each_input_event_time(monkeypatch):
    monkeypatch.setattr(state_cache_module.time, "time", lambda: 1_800_000_003.0)
    cache = SensorStateCache(required_sensors={"voltage", "current"})

    waiting = cache.update_with_status(
        "charger-5",
        "voltage",
        {"voltage": 230.0},
        sample_timestamp=1_800_000_002.0,
    )
    assert waiting.status == "waiting_for_all"

    aligned = cache.update_with_status(
        "charger-5",
        "current",
        {"current": 18.0},
        sample_timestamp=1_800_000_001.0,
    )

    assert aligned.input_timestamps == {
        "current": 1_800_000_001.0,
        "voltage": 1_800_000_002.0,
    }
    assert aligned.sample_timestamp == 1_800_000_002.0


def test_sensor_state_cache_reports_sensor_without_extractable_value():
    cache = SensorStateCache(required_sensors={"x", "y"})

    first = cache.update_with_status(
        "charger-4",
        "x",
        {"unrelated": 1.0, "other": 2.0},
    )
    assert first.status == "waiting_for_all"

    blocked = cache.update_with_status("charger-4", "y", {"y": 3.0})
    assert blocked.status == "waiting_for_all"
    assert blocked.missing_sensors == ("x",)

    recovered = cache.update_with_status("charger-4", "x", {"x": 4.0})
    assert recovered.status == "aligned_emit"
    assert recovered.features == {"x": 4.0, "y": 3.0}


@pytest.mark.parametrize(
    ("timestamp", "reason"),
    [
        (float("nan"), "observation_nonfinite"),
        (float("inf"), "observation_nonfinite"),
        (69.0, "observation_too_old"),
        (106.0, "observation_in_future"),
        (99.0, "observation_duplicate"),
        (98.0, "observation_regression"),
    ],
)
def test_rejected_observation_does_not_replace_latest_reading(
    monkeypatch, timestamp, reason
):
    monkeypatch.setattr(state_cache_module.time, "time", lambda: 100.0)
    cache = SensorStateCache({"a", "b"})
    cache.update_with_status("entity", "a", {"a": 1}, sample_timestamp=99.0)
    rejected = cache.update_with_status(
        "entity", "a", {"a": 999}, sample_timestamp=timestamp
    )
    assert rejected.status == "observation_rejected"
    assert rejected.rejection_reason == reason
    emitted = cache.update_with_status("entity", "b", {"b": 2}, sample_timestamp=100.0)
    assert emitted.features == {"a": 1, "b": 2}
    assert emitted.input_timestamps["a"] == 99.0


def test_observation_skew_blocks_until_compatible_new_observation(monkeypatch):
    monkeypatch.setattr(state_cache_module.time, "time", lambda: 100.0)
    cache = SensorStateCache({"a", "b"}, alignment_max_skew_seconds=2)
    cache.update_with_status("entity", "a", {"a": 1}, sample_timestamp=95)
    blocked = cache.update_with_status("entity", "b", {"b": 2}, sample_timestamp=100)
    assert blocked.status == "observation_skew_block"
    emitted = cache.update_with_status("entity", "a", {"a": 3}, sample_timestamp=100.1)
    assert emitted.features == {"a": 3, "b": 2}


def test_cached_observation_can_age_out_before_its_receipt_does(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(state_cache_module.time, "time", lambda: now[0])
    cache = SensorStateCache(
        {"a", "b"},
        max_sensor_age_seconds=30,
        observation_max_age_seconds=10,
        alignment_max_skew_seconds=30,
    )
    cache.update_with_status("entity", "a", {"a": 1}, sample_timestamp=91)
    now[0] = 102
    blocked = cache.update_with_status("entity", "b", {"b": 2}, sample_timestamp=102)
    assert blocked.status == "stale_sensor_block"
    assert blocked.stale_sensors == ("a",)
    assert blocked.sensor_ages["a"] == 2


def test_receipt_age_gates_scoring_even_when_observation_age_allows_delay(monkeypatch):
    monkeypatch.setattr(state_cache_module.time, "time", lambda: 100.0)
    monkeypatch.setattr(state_cache_module.time, "monotonic", lambda: 200.0)
    cache = SensorStateCache(
        {"a"}, max_sensor_age_seconds=1, observation_max_age_seconds=30
    )
    rejected = cache.update_with_status(
        "entity", "a", {"a": 1}, sample_timestamp=95, received_monotonic=195
    )
    assert rejected.rejection_reason == "receipt_too_old"
    assert cache.export_watermarks() == {}


def test_watermarks_survive_partial_frame_reset_without_reusing_cached_values(
    monkeypatch,
):
    monkeypatch.setattr(state_cache_module.time, "time", lambda: 100.0)
    original = SensorStateCache({"a", "b"})
    original.update_with_status("entity", "a", {"a": 1}, sample_timestamp=99)
    restored = SensorStateCache({"a", "b"})
    restored.restore_watermarks(original.export_watermarks())
    assert (
        restored.update_with_status(
            "entity", "a", {"a": 9}, sample_timestamp=99
        ).rejection_reason
        == "observation_duplicate"
    )
    waiting = restored.update_with_status("entity", "b", {"b": 2}, sample_timestamp=100)
    assert waiting.status == "waiting_for_all"
    assert waiting.missing_sensors == ("a",)
    assert restored.update_with_status(
        "entity", "a", {"a": 3}, sample_timestamp=100
    ).features == {"a": 3, "b": 2}


def test_subsecond_freshness_is_not_silently_clamped(monkeypatch):
    monkeypatch.setattr(state_cache_module.time, "time", lambda: 100.0)
    monkeypatch.setattr(state_cache_module.time, "monotonic", lambda: 200.0)
    cache = SensorStateCache({"a"}, max_sensor_age_seconds=0.01)
    rejected = cache.update_with_status(
        "entity", "a", {"a": 1}, received_monotonic=199.98
    )
    assert rejected.rejection_reason == "receipt_too_old"
