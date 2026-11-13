"""Pin the hashes that decide whether a saved detector state may be restored.

A changed digest silently discards every checkpoint written by the previous
release, so each one is a literal here. They last changed when last-known-value
alignment replaced the strict barrier, which changes every monitor's input.
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
        minimum_hold_seconds=20.0,
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
        hold_intervals=2.5,
    )


def _pipeline():
    return AnomalyDetectionConfig(
        pipeline=minimal_static_execution(),
        subscription_topics=["telemetry/entity/a"],
    )


def test_static_detector_schema_signature_is_unchanged():
    assert (
        StaticConformalDetectionService._build_schema_signature_from_config(_static())
        == "d2c81cd9dabe0eba38bea6024e9b21be44eca72119c4af39cb7e1cbac7c2de03"
    )


def test_adaptive_detector_schema_signature_requires_relearning_on_upgrade():
    # Includes the installed Aberrant version: an upgrade invalidates states.
    assert AdaptiveStreamDetectionService._build_schema_signature(_adaptive()) == (
        "b003fb768bd493a845e0155ea9b4e0765dfe65dbc1f00a0b7bc07ea96997268e"
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
        "static": "637ffafe60e52e798353308ea399d5212063dc73a7457ceaea6e76c66103340a",
        # The explicit library version is the migration boundary: 1.4.0 -> 1.5.0.
        "adaptive": "01319902a4cf80aef44ba730acb827273f7b04042053f7ebf47f8c36e0258921",
        "pipeline": "2836dbeed6e86737c1b6a205d39947f3448a004d8ad3d1cb25a66cf737a7b909",
    }
