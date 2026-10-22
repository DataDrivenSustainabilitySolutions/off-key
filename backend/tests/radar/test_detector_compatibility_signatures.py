"""Pin the hashes that decide whether a saved detector state may be restored.

A changed digest silently discards every checkpoint written by the previous
release, so each one is a literal here.
"""

from off_key_core.schemas.radar import AdaptiveStreamConfig, StaticBaselineConfig
from off_key_mqtt_radar.adaptive_detector import AdaptiveStreamDetectionService
from off_key_mqtt_radar.config.config import AnomalyDetectionConfig
from off_key_mqtt_radar.detector import StaticConformalDetectionService
from off_key_mqtt_radar.runtime_checkpoint import RuntimeCheckpointCodec

from tests.support.pipelines import minimal_static_execution

TOPICS = ["telemetry/c1/L2", "telemetry/c1/L1"]


def _static():
    return AnomalyDetectionConfig(
        monitoring=StaticBaselineConfig(
            model_type="pyod_knn",
            model_params={"n_neighbors": 7, "contamination": 0.08},
            training_window_size=20,
            calibration_window_size=5,
        ),
        subscription_topics=TOPICS,
        sensor_freshness_seconds=20.0,
    )


def _adaptive():
    return AnomalyDetectionConfig(
        monitoring=AdaptiveStreamConfig(
            model_type="aberrant_online_isolation_forest",
            model_params={"num_trees": 2},
            training_window_size=1200,
            calibration_window_size=360,
        ),
        subscription_topics=TOPICS,
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
        == "f84508e7fffed6715b68161d0d05547d039f09e46927df84f1b80004ffc25d22"
    )


def test_adaptive_detector_schema_signature_is_unchanged():
    # Includes the installed Aberrant version: an upgrade invalidates states.
    assert AdaptiveStreamDetectionService._build_schema_signature(_adaptive()) == (
        "aa73ec5d160882af7cd6aea28879469921af07c0848991a9d67908802deb7bc0"
    )


def test_runtime_checkpoint_configuration_fingerprint_is_unchanged():
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
        "static": "db94415b399249ae985510db0562336d6ae4e6ac37a73596e51ecc015d304675",
        "adaptive": "e75494dee6103b58052a94ab794be1233b039c985d33d87d65d5a127515d3d33",
        "pipeline": "d4f00448d44de0e86c95f0e553a0fa20f189e1ad6bf4878cd59ed3ce6c323c21",
    }
