"""Capture a real old-runtime checkpoint; run only in the 1.3 production image.

Build backend/Dockerfile from off-key b5c6dd3c with SERVICE_NAME=off-key-mqtt-radar
and SERVICE_ROOT=services/mqtt/radar. Mount that revision's backend/tests on
/source/tests, set PYTHONPATH=/source, and run this script with the output path.
The disposable test authentication key is deliberately public.
"""

import base64
import json
import sys
from importlib.metadata import version
from pathlib import Path

from off_key_mqtt_radar.adaptive_detector import AdaptiveStreamDetectionService
from off_key_mqtt_radar.config.config import MQTTRadarConfig
from off_key_mqtt_radar.runtime_checkpoint import (
    RuntimeCheckpoint,
    RuntimeCheckpointCodec,
)

from tests.support.form_pipeline import form_launch

SECRET = b"disposable-integration-checkpoint-key"


def main():
    assert version("aberrant") == "1.3.0"
    launch = form_launch(
        container_name="aberrant-upgrade-reference",
        strategy="adaptive_stream",
        mqtt_topics=["telemetry/entity/x"],
        adaptive_stream_config={
            "model_type": "aberrant_moving_average",
            "model_params": {"window_size": 8},
            "training_window_size": 2,
            "calibration_window_size": 3,
        },
    )
    config = MQTTRadarConfig(pipeline=launch.pipeline)
    detector = AdaptiveStreamDetectionService(config)
    for value in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0):
        detector.process_data_point({"x": value})
    assert detector.state.value == "operational"
    codec = RuntimeCheckpointCodec("aberrant-upgrade-reference", config, SECRET)
    record = codec.encode(RuntimeCheckpoint(detector=detector.export_checkpoint()))
    assert codec.decode(record).detector["processed_count"] == 6
    record["payload"] = base64.b64encode(record["payload"]).decode()
    record["saved_at"] = record["saved_at"].isoformat()
    fixture = {
        "source_revision": "b5c6dd3c",
        "runtime_versions": {
            name: version(name)
            for name in ("aberrant", "numpy", "scipy", "scikit-learn", "nonconform")
        },
        "launch": launch.model_dump(mode="json"),
        "checkpoint": record,
    }
    Path(sys.argv[1]).write_text(json.dumps(fixture, indent=2) + "\n")


if __name__ == "__main__":
    main()
