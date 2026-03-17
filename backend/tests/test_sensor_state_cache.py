"""Tests for sensor alignment cache freshness gating."""

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
    second = cache.update_with_status("charger-1", "cosine", {"cosine": 2.0})
    assert second.status == "aligned_emit"
    assert second.features == {"sine": 1.0, "cosine": 2.0}

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

    cache = SensorStateCache(
        required_sensors={"x", "y"},
        alignment_mode="strict_barrier",
    )

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
