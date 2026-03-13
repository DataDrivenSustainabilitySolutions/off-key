"""Simulation test for multi-sensor cadence alignment behavior."""

from off_key_mqtt_radar import state_cache as state_cache_module
from off_key_mqtt_radar.message_processor import MessageProcessor
from off_key_mqtt_radar.state_cache import SensorStateCache


def test_three_sensor_cadence_simulation_blocks_stale_vectors(monkeypatch):
    now = {"value": 100.0}

    def _fake_time() -> float:
        return now["value"]

    monkeypatch.setattr(state_cache_module.time, "time", _fake_time)

    class _Detector:
        @staticmethod
        def process_with_resilience(*args, **kwargs):
            return None

    class _Validator:
        @staticmethod
        def validate_and_sanitize(data):
            return data

    class _MemoryManager:
        @staticmethod
        def should_cleanup():
            return False

    detector = _Detector()
    security_validator = _Validator()
    memory_manager = _MemoryManager()

    cache = SensorStateCache(
        required_sensors={"s1", "s2", "s3"},
        max_sensor_age_seconds=5.0,
    )
    processor = MessageProcessor(
        detector=detector,  # detector is unused in this alignment-focused simulation
        security_validator=security_validator,
        memory_manager=memory_manager,
        state_cache=cache,
        required_sensors={"s1", "s2", "s3"},
    )

    statuses = []

    features, alignment = processor._align_features("charger-1", "s1", {"s1": 1.0})
    statuses.append(alignment["alignment_status"])
    assert features is None

    now["value"] = 101.0
    features, alignment = processor._align_features("charger-1", "s2", {"s2": 2.0})
    statuses.append(alignment["alignment_status"])
    assert features is None

    now["value"] = 102.0
    features, alignment = processor._align_features("charger-1", "s3", {"s3": 3.0})
    statuses.append(alignment["alignment_status"])
    assert features == {"s1": 1.0, "s2": 2.0, "s3": 3.0}

    # s1 arrives late; s2 and s3 are now stale and must be blocked.
    now["value"] = 110.0
    features, alignment = processor._align_features("charger-1", "s1", {"s1": 1.1})
    statuses.append(alignment["alignment_status"])
    assert features is None
    assert alignment["alignment_status"] == "stale_sensor_block"

    now["value"] = 111.0
    features, alignment = processor._align_features("charger-1", "s2", {"s2": 2.1})
    statuses.append(alignment["alignment_status"])
    assert features is None
    assert alignment["alignment_status"] == "stale_sensor_block"

    # Once the slow sensor recovers, aligned vectors resume.
    now["value"] = 112.0
    features, alignment = processor._align_features("charger-1", "s3", {"s3": 3.1})
    statuses.append(alignment["alignment_status"])
    assert features == {"s1": 1.1, "s2": 2.1, "s3": 3.1}

    assert statuses == [
        "waiting_for_all",
        "waiting_for_all",
        "aligned_emit",
        "stale_sensor_block",
        "stale_sensor_block",
        "aligned_emit",
    ]
