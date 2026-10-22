"""Pin the TACTIC-to-RADAR environment so refactors cannot drift it.

The emitted dict is the input to ``build_radar_config_fingerprint``, which is
persisted per service and in workload labels. Any change to a key or to its
string formatting makes running monitors look reconfigured.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from off_key_core.models.pipelines import compile_pipeline, execution_fingerprint
from off_key_core.schemas.pipelines import PipelineDefinition, PipelineExecutionConfig
from off_key_core.schemas.radar import RadarStartConfig
from off_key_core.utils.mqtt_topics import derive_monitoring_sensor_keys
from off_key_mqtt_radar.admission import RadarAdmissionSettings
from off_key_mqtt_radar.config.config import RadarSettings
from off_key_mqtt_radar.config.runtime import (
    RadarCheckpointSettings,
    RadarDatabaseSettings,
    RadarRuntimeFileSettings,
)
from off_key_mqtt_radar.preflight import PreflightSettings
from off_key_tactic_middleware.config.config import RadarDefaultsConfig, TacticSettings
from off_key_tactic_middleware.services.orchestration.radar_environment import (
    build_radar_config_fingerprint,
    build_radar_environment,
)
from pydantic import SecretStr

MODULE = "off_key_tactic_middleware.services.orchestration.radar_environment"
RADAR_SETTINGS = (
    RadarSettings,
    RadarDatabaseSettings,
    RadarCheckpointSettings,
    RadarRuntimeFileSettings,
    RadarAdmissionSettings,
    PreflightSettings,
)
# TACTIC-private keys travelling in the same dict, and keys RADAR may stop
# reading while TACTIC keeps emitting them so fingerprints stay stable.
NOT_READ_BY_RADAR = {
    "RADAR_RUNTIME_IMAGE",
    "RADAR_COLLECTION_FINGERPRINT",
    "RADAR_BATCH_SIZE",
    "RADAR_BATCH_TIMEOUT",
}
# RadarDefaultsConfig fields whose RADAR name is not RADAR_<FIELD>.
RADAR_NAMES = {"mqtt_qos": "RADAR_SUBSCRIPTION_QOS"}
GOLDEN_FINGERPRINTS = {
    "static": "8cbbc852af961f6758434329ab48baa7a9f64293ba7a4092a312a69fdd690c15",
    "adaptive": "85a99b62a0f414ee1e9aa2be78fcd25d780636b4fad2ca1be46c12c30a7826be",
    "pipeline": "37c1d6eb6eafa0b78256f464c20f737baaa6f821aa7f72458dec004805c818f8",
}


def _static_config():
    return RadarStartConfig(
        container_name="radar-static",
        mqtt_topics=["telemetry/c1/L1", "telemetry/c1/L2"],
        strategy="static_baseline",
        model_type="pyod_iforest",
        model_params={"n_estimators": 100},
        mqtt_config={"qos": 1, "client_id_prefix": "golden"},
        performance_config={
            "sensor_key_strategy": "leaf",
            "sensor_freshness_seconds": 20.0,
        },
        static_baseline_config={
            "model_params": {"n_estimators": 100},
            "training_window_size": 120,
            "calibration_window_size": 30,
        },
        runtime_image="ghcr.io/example/radar@sha256:" + "a" * 64,
    )


def _adaptive_config():
    return RadarStartConfig(
        container_name="radar-adaptive",
        mqtt_topics=["telemetry/charger-1/L1"],
        strategy="adaptive_stream",
        model_type="aberrant_online_isolation_forest",
        model_params={"num_trees": 2},
        adaptive_stream_config={
            "model_params": {"num_trees": 2},
            "training_window_size": 1200,
            "calibration_window_size": 360,
        },
    )


def _pipeline_config():
    definition = compile_pipeline(
        PipelineDefinition.model_validate(
            dict(
                strategy="static_baseline",
                input_slots=[dict(id="a", label="Power")],
                nodes=[
                    dict(id="input", kind="source", component="source.aligned"),
                    dict(
                        id="model",
                        kind="detector",
                        component="detector:pyod_iforest",
                        params={"n_estimators": 10},
                    ),
                    dict(id="policy", kind="policy", component="policy.martingale"),
                    dict(id="output", kind="output", component="output.evidence"),
                ],
                edges=[
                    dict(source="input", target="model"),
                    dict(source="model", target="policy"),
                    dict(source="policy", target="output"),
                ],
                settings=dict(training_window_size=20, calibration_window_size=5),
            )
        )
    ).definition
    bindings = [
        dict(
            slot_id="a",
            reading_id="r-a",
            entity_id="entity",
            accepted_topic="telemetry/entity/a",
            input_key=derive_monitoring_sensor_keys(
                ["telemetry/entity/a"], sensor_key_strategy="full_hierarchy"
            )[0],
        )
    ]
    return RadarStartConfig(
        container_name="radar-pipeline",
        mqtt_topics=["telemetry/entity/a"],
        pipeline=PipelineExecutionConfig(
            definition=definition,
            bindings=bindings,
            fingerprint=execution_fingerprint(definition, bindings),
            revision_id="revision",
            run_id="run",
        ),
    )


CONFIGS = {
    "static": _static_config,
    "adaptive": _adaptive_config,
    "pipeline": _pipeline_config,
}


def _environment(config):
    settings = SimpleNamespace(
        config=SimpleNamespace(radar_defaults=RadarDefaultsConfig())
    )
    runtime = SimpleNamespace(
        ENVIRONMENT="development",
        radar_database_url="postgresql+asyncpg://radar:secret@postgres/radar",
        RADAR_CHECKPOINT_SECRET=SecretStr("golden-checkpoint-secret"),
    )
    with (
        patch(f"{MODULE}.get_tactic_settings", return_value=settings),
        patch(f"{MODULE}.get_radar_container_runtime_settings", return_value=runtime),
    ):
        return build_radar_environment(
            service_id="svc-golden", config=config, model_registry=None
        )


@pytest.mark.parametrize("name", CONFIGS)
def test_every_emitted_key_is_read_by_radar(name):
    environment = _environment(CONFIGS[name]())
    environment["RADAR_COLLECTION_FINGERPRINT"] = "collection"
    environment["RADAR_LIFECYCLE_VERSION"] = "1"
    radar_fields = set().union(*(model.model_fields for model in RADAR_SETTINGS))

    assert not set(environment) - radar_fields - NOT_READ_BY_RADAR


def test_tactic_defaults_match_radar_defaults():
    radar_fields = RadarSettings.model_fields
    tactic_fields = TacticSettings.model_fields
    for name, field in RadarDefaultsConfig.model_fields.items():
        assert tactic_fields[f"TACTIC_RADAR_DEFAULT_{name.upper()}"].default == (
            field.default
        ), name
        if name == "model_type":
            # RADAR reads the model from RADAR_MONITORING_CONFIG instead.
            continue
        radar_name = RADAR_NAMES.get(name, f"RADAR_{name.upper()}")
        assert radar_fields[radar_name].default == field.default, name


@pytest.mark.parametrize("name", CONFIGS)
def test_environment_fingerprint_is_unchanged(name):
    environment = _environment(CONFIGS[name]())

    assert build_radar_config_fingerprint(environment) == GOLDEN_FINGERPRINTS[name], (
        "The RADAR environment changed. Running monitors would look reconfigured: "
        + json.dumps(environment, sort_keys=True, indent=1)
    )
