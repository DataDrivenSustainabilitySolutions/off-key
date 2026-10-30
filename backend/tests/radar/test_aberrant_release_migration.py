"""A real 1.3 checkpoint cannot bypass 1.4 relearning and recalibration."""

import base64
import json
from copy import deepcopy
from pathlib import Path

import pytest
from off_key_mqtt_radar.adaptive_detector import (
    AdaptiveStreamDetectionService,
    AdaptiveStreamState,
)
from off_key_mqtt_radar.config.config import MQTTRadarConfig
from off_key_mqtt_radar.runtime_checkpoint import RuntimeCheckpointCodec
from off_key_tactic_middleware.services.pipelines.release import normalize_saved_launch

pytestmark = pytest.mark.radar_integration

SECRET = b"disposable-integration-checkpoint-key"


def test_authentic_1_3_checkpoint_requires_fresh_learning(monkeypatch):
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/aberrant-1.3-checkpoint.json").read_text()
    )
    assert fixture["runtime_versions"]["aberrant"] == "1.3.0"
    original = deepcopy(fixture["launch"])
    launch = normalize_saved_launch(fixture["launch"])
    assert fixture["launch"] == original
    assert launch.pipeline.model_dump(mode="json") == original["pipeline"]
    assert launch.monitoring.aberrant_version == "1.4.0"
    config = MQTTRadarConfig(pipeline=launch.pipeline)
    record = fixture["checkpoint"]
    record["payload"] = base64.b64decode(record["payload"], validate=True)
    assert record["processed_count"] == 6
    codec = RuntimeCheckpointCodec("aberrant-upgrade-reference", config, SECRET)

    def reject_deserialization(*_args):
        pytest.fail("The previous runtime's learned state was deserialized")

    monkeypatch.setattr(
        "off_key_mqtt_radar.runtime_checkpoint.pickle.loads", reject_deserialization
    )
    # Authentication must succeed before this incompatible-runtime rejection.
    with pytest.raises(ValueError, match="incompatible"):
        codec.decode(record)
    detector = AdaptiveStreamDetectionService(config)
    assert detector.state == AdaptiveStreamState.WARMUP
    assert detector.processed_count == detector.calibration_count == 0
    assert detector.threshold is None
    for value in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0):
        detector.process_data_point({"x": value})
    assert detector.state == AdaptiveStreamState.OPERATIONAL
    assert detector.warmup_count == 2
    assert detector.calibration_count == 3
    assert detector.threshold is not None
