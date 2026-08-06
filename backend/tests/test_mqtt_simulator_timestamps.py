from datetime import UTC, datetime

from off_key_mqtt_simulator.__main__ import SimulatorService
from off_key_mqtt_simulator.config import SimulatorSettings


def test_simulator_reuses_one_sampling_timestamp_across_sensor_payloads():
    service = SimulatorService(SimulatorSettings(_env_file=None).config)
    sample_timestamp = datetime(2026, 8, 6, 10, 0, 0, 123456, tzinfo=UTC)

    sine = service._build_payload("charger-1", "sine", 1.0, sample_timestamp)
    cosine = service._build_payload("charger-1", "cosine", 2.0, sample_timestamp)

    assert sine["timestamp"] == "2026-08-06T10:00:00.123456Z"
    assert cosine["timestamp"] == sine["timestamp"]
