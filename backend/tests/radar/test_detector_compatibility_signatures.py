"""Pin the hashes that decide whether a saved detector state may be restored.

A changed digest silently discards every checkpoint written by the previous
release, so each one is a literal here.
"""

from off_key_core.schemas.radar import AdaptiveStreamConfig, StaticBaselineConfig
from off_key_mqtt_radar.adaptive_detector import AdaptiveStreamDetectionService
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig
from off_key_mqtt_radar.detector import StaticConformalDetectionService
from off_key_mqtt_radar.runtime_checkpoint import RuntimeCheckpointCodec

from tests.support.form_pipeline import form_radar_config
from tests.support.pipelines import minimal_static_execution

TOPICS = ["telemetry/c1/L2", "telemetry/c1/L1"]


def _static():
    return form_radar_config(
        StaticBaselineConfig(
            model_type="pyod_knn",
            model_params={"n_neighbors": 7, "contamination": 0.08},
            training_window_size=20,
            calibration_window_size=5,
        ),
        TOPICS,
        sensor_freshness_seconds=20.0,
    )


def _adaptive():
    return form_radar_config(
        AdaptiveStreamConfig(
            model_type="aberrant_online_isolation_forest",
            model_params={"num_trees": 2},
            training_window_size=1200,
            calibration_window_size=360,
        ),
        TOPICS,
        alignment_max_skew_seconds=2.5,
    )


def _pipeline():
    return AnomalyDetectionConfig(
        pipeline=minimal_static_execution(),
        subscription_topics=["telemetry/entity/a"],
    )


def test_static_detector_schema_signature_is_unchanged():
    assert (
        StaticConformalDetectionService._build_schema_signature_from_config(_static())
        == "b0f51a0f8f43c57ce52495035991203a6a537449be6109b3a323999e525eebee"
    )


def test_adaptive_detector_schema_signature_requires_relearning_on_upgrade():
    # Includes the installed Aberrant version: an upgrade invalidates states.
    assert AdaptiveStreamDetectionService._build_schema_signature(_adaptive()) == (
        "1550e554e96260bc0ee7b1f456be74fea9360bd5ba4f260675b656fe09840f9d"
    )


def test_checkpoint_fingerprints_preserve_static_and_upgrade_adaptive():
    fingerprints = {
        name: RuntimeCheckpointCodec(
            "svc", config(), b"secret"
        ).configuration_fingerprint
        for name, config in (
            ("static", _static),
            ("adaptive", _adaptive),
            ("pipeline", _pipeline),
        )
    }

    assert fingerprints == {
        "static": "8a48accbec59655e0409bcd2955797ae1049ea94c166853a9a9dbbc33994e176",
        # The explicit library version is the migration boundary: 1.4.0 -> 1.5.0.
        "adaptive": "a849083eda0ac55415f7e48cbb462356ff4b912f517c3c012f97af7a9fcfbc9d",
        "pipeline": "d4f00448d44de0e86c95f0e553a0fa20f189e1ad6bf4878cd59ed3ce6c323c21",
    }
